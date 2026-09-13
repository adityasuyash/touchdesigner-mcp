"""One-off setup of the TouchDesigner install itself.

Two things about a stock TouchDesigner make this system awkward, and neither is
fixable from inside a project:

  * **It renames the project on every save.** `project.toe` becomes
    `project.1.toe`, then `project.2.toe`. Every workspace guard that wants to
    answer "is TouchDesigner running *this* song?" has to cope with a filename
    that changes underneath it.
  * **The MCP server has to be dragged into each project by hand.** It is the
    transport; a project without it cannot be driven at all.

These are preferences and files on the machine, not repo state, so they are
applied by running this module deliberately rather than as a side effect of
starting the UI. Everything it changes is recorded first, so `--undo` restores
what was actually there instead of guessing at defaults.

    python -m lyricfield.td_setup            apply
    python -m lyricfield.td_setup --status   report, change nothing
    python -m lyricfield.td_setup --undo     put it all back
    python -m lyricfield.td_setup --make-template   regenerate the template only

There is no TouchDesigner hook that injects a component into every project, so
"the server is always there" is reached three ways at once: the custom startup
file covers launching TouchDesigner, the user palette covers any project you open
by hand (one drag), and lyricfield's own provisioning inherits it from the
template.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .td_client import TDClient, TDUnavailable

REPO = Path(__file__).resolve().parents[1]
TOX = REPO / "td_mcp_server.tox"

STATE = Path.home() / ".config" / "lyricfield" / "td_setup.json"
TEMPLATE = Path.home() / "lyricfield-projects" / "_template.toe"
# The template's source of truth, kept expanded as text so the repo stays
# diffable. `toecollapse` rebuilds the .toe from it.
TEMPLATE_SRC = REPO / "templates" / "_template.toe.dir"
SERVER_SRC = REPO / "scripts" / "td_mcp_server.py"

SERVER_COMP = "td_mcp_server"
ROOT = "/project1"

# The preferences we touch. The Preferences dialog names them "Increment
# Filename when Saving" (Off / On / On and Copy to Backup Folder) and "Startup
# File Mode" (default project / empty project / custom project), but the docs
# never say which integer is which -- so the values below are a starting guess
# that `apply` verifies by behaviour and corrects if wrong.
PREF_INC = "general.inc"
PREF_STARTUP_MODE = "general.startupfilemode"
PREF_STARTUP_FILE = "general.startupfilename"


def _run(client: TDClient, body: str, timeout: float | None = None) -> str:
    """Run a function body inside TD. Wrapped because the server's exec scope
    gives module-level names no visibility inside nested defs."""
    return client.run("def main():\n" + body + "\nprint(main())", timeout=timeout)


# --------------------------------------------------------------------- state

@dataclass
class Saved:
    """What the machine looked like before we touched it, and what is done.

    Per item rather than one flag: an earlier version recorded `applied` after
    completing only half the work, and every later call then short-circuited on
    it -- so the half that mattered could never run.
    """
    prefs: dict = field(default_factory=dict)
    palette_file: str = ""          # the tox we copied in, if we created it
    template: str = ""
    inc_settled: bool = False       # saving no longer renames the project
    startup_set: bool = False       # TD launches on the template
    palette_installed: bool = False
    applied: bool = False           # any of the above; kept for --undo

    @property
    def complete(self) -> bool:
        return self.inc_settled and self.startup_set and self.palette_installed

    @classmethod
    def load(cls) -> "Saved":
        try:
            return cls(**json.loads(STATE.read_text()))
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        STATE.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        STATE.write_text(json.dumps(self.__dict__, indent=2) + "\n")


# ---------------------------------------------------------------- preferences

def read_prefs(client: TDClient, keys: list[str]) -> dict:
    out = _run(client, f"""
    return repr({{k: ui.preferences[k] for k in {keys!r}}})
""")
    try:
        return eval(out.strip())
    except Exception:
        return {}


def all_prefs(client: TDClient) -> dict:
    out = _run(client, """
    return repr({k: ui.preferences[k] for k in ui.preferences})
""")
    try:
        return eval(out.strip())
    except Exception:
        return {}


def write_prefs(client: TDClient, values: dict) -> dict:
    """Set preferences and persist them. Returns what they read back as.

    `ui.preferences.save()` is required: without it the change is lost at the
    next launch, which would make this whole module look like it silently did
    nothing.
    """
    out = _run(client, f"""
    vals = {values!r}
    for k, v in vals.items():
        ui.preferences[k] = v
    ui.preferences.save()
    return repr({{k: ui.preferences[k] for k in vals}})
""")
    try:
        return eval(out.strip())
    except Exception:
        return {}


# ------------------------------------------------------------------ behaviour

def increments_on_save(client: TDClient, timeout: float = 420.0) -> bool | None:
    """Does a save rename the project? Measured, not assumed.

    Saves the open project to *its own current path*, read first and passed back
    as a concrete string. That is both explicit -- it can never overwrite some
    other project the way `project.folder + project.name` evaluated inside
    TouchDesigner could -- and a fair test: saving to any other path is a
    save-as, which changes the name whatever the preference says, so every
    candidate would read as "renames".
    """
    before = _run(client, """
    import os
    return os.path.join(project.folder, project.name)
""").strip()
    if not before:
        return None
    from . import sync
    sync.quiesce(client)
    try:
        _run(client, f"""
    project.save({before!r})
    return 'saved'
""", timeout=timeout)
    except Exception:
        if not client.wait_until_ready(seconds=timeout):
            return None
    after = _run(client, """
    import os
    return os.path.join(project.folder, project.name)
""").strip()
    if not after:
        return None
    return after != before


def settle_increment_pref(client: TDClient, say=print) -> int | None:
    """Find the `general.inc` value that actually stops the renaming.

    The dialog offers three settings and the docs do not say which integer is
    which, so try them lowest-first and keep the first that measurably stops a
    save from moving the file.
    """
    for candidate in (0, 1, 2):
        write_prefs(client, {PREF_INC: candidate})
        incr = increments_on_save(client)
        if incr is None:
            say(f"  {PREF_INC}={candidate}: could not measure (TD did not answer)")
            return None
        say(f"  {PREF_INC}={candidate}: save {'renames' if incr else 'keeps the filename'}")
        if not incr:
            return candidate
    return None


# -------------------------------------------------------------------- palette

def install_palette(client: TDClient, say=print) -> str:
    """Put the server component in the user palette, so it is one drag away in
    any project -- including projects this system did not create."""
    folder = _run(client, """
    return app.userPaletteFolder
""").strip()
    if not folder:
        raise RuntimeError("TouchDesigner did not report a user palette folder")
    dst = Path(folder) / TOX.name
    if not TOX.exists():
        raise RuntimeError(f"{TOX} is missing; rebuild it before running setup")
    dst.parent.mkdir(parents=True, exist_ok=True)
    existed = dst.exists()
    shutil.copy2(TOX, dst)
    say(f"  user palette {'updated' if existed else 'installed'}: {dst}")
    return "" if existed else str(dst)


# ------------------------------------------------------------------- template

def make_template(client: TDClient, path: Path = TEMPLATE, say=print,
                  reload_original: bool = True) -> tuple[Path, str]:
    """Write a project containing only the MCP server.

    The live project is saved first, then re-pointed at the template path and
    stripped, then the original is loaded back. Doing it in that order means a
    crash at any point leaves the original file on disk intact -- the stripping
    only ever happens to a project already writing to the template path.
    """
    from . import sync

    original = _run(client, """
    import os
    return os.path.join(project.folder, project.name)
""").strip()
    if not original:
        raise RuntimeError("could not determine which project is open")
    say(f"  current project: {original}")

    has_server = _run(client, f"""
    return repr(op({ROOT + '/' + SERVER_COMP!r}) is not None)
""").strip()
    if has_server != "True":
        raise RuntimeError(
            f"the open project has no {ROOT}/{SERVER_COMP}; cannot make a template "
            "from it. Drag td_mcp_server.tox into the project first."
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    sync.quiesce(client)

    say("  saving the current project before touching anything")
    _safe_save(client, original)

    say(f"  writing {path}")
    _safe_save(client, str(path))

    say("  stripping everything except the server")
    kept = _run(client, f"""
    root = op({ROOT!r})
    dropped = 0
    for c in list(root.children):
        if c.name != {SERVER_COMP!r}:
            try:
                c.destroy()
                dropped += 1
            except Exception:
                pass
    return repr((dropped, [c.name for c in root.children]))
""", timeout=180.0)
    say(f"  removed {kept}")

    # Neutralise the timeline before saving. A template inherits the length and
    # play range of whatever project it was cut from -- traced back to a 90s
    # benchmark track, which then propagated into every song forked from it and
    # silently capped the playhead at frame 5433. Provisioning sets the real
    # length per song, but the template should not be carrying one song's shape
    # into the next one's project.
    say("  resetting the timeline so no song's length is baked in")
    _run(client, """
    t = op('/local/time')
    t.end = 600
    t.par.rangestart = 1
    t.par.rangeend = 600
    return '%s..%s of %s' % (t.par.rangestart.eval(), t.par.rangeend.eval(), t.end)
""")
    _safe_save(client, str(path))

    if reload_original:
        say(f"  reloading {original}")
        load_project(client, original)
    return path, original


def _safe_save(client: TDClient, target: str, timeout: float = 420.0) -> None:
    """Save, tolerating the stall. TD routinely stops answering mid-save for
    minutes and then completes normally."""
    try:
        _run(client, f"""
    project.save({target!r})
    return project.name
""", timeout=timeout)
    except Exception:
        if not client.wait_until_ready(seconds=timeout):
            raise


def load_project(client: TDClient, path: str, timeout: float = 420.0) -> None:
    """Open a project, then wait for the MCP server to come back with it.

    Loading a project kills the server -- it lives inside the project. It only
    returns if the project being loaded contains one, so this must never be
    pointed at a file that has not been checked.
    """
    try:
        _run(client, f"""
    project.load({path!r})
    return 'loading'
""", timeout=30.0)
    except Exception:
        pass            # the server goes down mid-call; that is expected
    if not client.wait_until_ready(seconds=timeout):
        raise TDUnavailable(
            f"TouchDesigner did not come back after loading {path}. If that "
            "project has no td_mcp_server component, reopen one that does."
        )


def template_is_sane(client: TDClient, path: Path = TEMPLATE) -> tuple[bool, str]:
    """Is the template a project containing the server and little else?"""
    if not path.exists():
        return False, f"{path} does not exist"
    return True, f"{path} ({path.stat().st_size // 1024} KB)"


def collapse_template(dest: Path = TEMPLATE, src: Path = TEMPLATE_SRC,
                      say=print) -> Path:
    """Rebuild the template .toe from the expanded text kept in the repo."""
    import shutil
    import subprocess
    import tempfile

    toc = src.with_suffix(".toe.toc")
    if not src.exists() or not toc.exists():
        raise FileNotFoundError(
            f"no expanded template at {src} (and its .toc). Regenerate one with "
            "--make-template from a project that has the server in it."
        )
    exe = None
    for cand in (Path("/Applications/TouchDesigner.app/Contents/MacOS/toecollapse"),
                 Path("/opt/TouchDesigner/bin/toecollapse"),
                 Path("C:/Program Files/Derivative/TouchDesigner/bin/toecollapse.exe")):
        if cand.exists():
            exe = cand
            break
    if exe is None:
        raise FileNotFoundError("toecollapse not found in the TouchDesigner install")

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shutil.copytree(src, work / dest.name.replace(".toe", ".toe.dir"))
        shutil.copy2(toc, work / dest.name.replace(".toe", ".toe.toc"))
        subprocess.run([str(exe), dest.name], cwd=work, check=True,
                       capture_output=True, timeout=180)
        built = work / dest.name
        if not built.exists():
            raise RuntimeError(f"toecollapse produced no {dest.name}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(built, dest)
    say(f"  template rebuilt from text: {dest}")
    return dest


def launch_touchdesigner(client: TDClient, project: Path = TEMPLATE,
                         say=print, timeout: float = 240.0) -> bool:
    """Start TouchDesigner on a project known to contain the server."""
    import subprocess
    import sys as _sys

    if not project.exists():
        return False
    say(f"  starting TouchDesigner on {project.name}")
    try:
        if _sys.platform == "darwin":
            subprocess.run(["open", "-a", "TouchDesigner", str(project)],
                           check=True, capture_output=True)
        else:
            subprocess.Popen(["TouchDesigner", str(project)])
    except (OSError, subprocess.SubprocessError) as e:
        say(f"  could not start TouchDesigner: {e}")
        return False
    return client.wait_until_ready(seconds=timeout)


def refresh_server(client: TDClient, say=print) -> bool:
    """Push the repo's server source into the running project's handler DAT.

    The template carries a frozen copy of the server from whenever it was made,
    so a project started from it would otherwise run stale server code.
    """
    from . import sync

    if not SERVER_SRC.exists():
        return False
    handler = f"{ROOT}/{SERVER_COMP}/mcp_handler"
    try:
        current = client.dat_text(handler)
    except Exception:
        return False
    wanted = SERVER_SRC.read_text()
    if current.strip() == wanted.strip():
        return False
    client.write(handler, wanted)
    say("  refreshed the MCP server handler from the repo")
    return True


def ensure(client: TDClient | None = None, say=print,
           launch: bool = True, prefs: bool = True) -> dict:
    """Make the environment ready. Idempotent; safe to call at every run.

    This is what replaces remembering to run setup: each piece is checked and
    only done if it is actually missing.
    """
    from .td_client import TDClient as _TDClient

    client = client or _TDClient()
    report: dict = {"launched": False, "template": None, "palette": None,
                    "prefs": None, "server_refreshed": False}

    if not TEMPLATE.exists():
        try:
            collapse_template(TEMPLATE, say=say)
            report["template"] = "rebuilt from text"
        except Exception as e:
            say(f"  no template available: {e}")
            report["template"] = f"unavailable: {e}"
    else:
        report["template"] = "present"

    if not client.ping():
        if not launch:
            raise TDUnavailable("TouchDesigner is not running")
        if not launch_touchdesigner(client, TEMPLATE, say=say):
            raise TDUnavailable(
                "TouchDesigner did not start, or started without the MCP server. "
                f"Open {TEMPLATE} by hand once and re-run."
            )
        report["launched"] = True

    report["server_refreshed"] = refresh_server(client, say=say)

    saved = Saved.load()
    if not saved.prefs:
        saved.prefs = read_prefs(
            client, [PREF_INC, PREF_STARTUP_MODE, PREF_STARTUP_FILE])

    if not saved.palette_installed:
        try:
            made = install_palette(client, say=say)
            saved.palette_file = made or saved.palette_file
            saved.palette_installed = True
            report["palette"] = made or "already present"
        except Exception as e:
            report["palette"] = f"skipped: {e}"
    else:
        report["palette"] = "already installed"

    if prefs and not saved.startup_set:
        say("pointing TouchDesigner's startup file at the template")
        mode = _settle_startup_mode(client, say)
        saved.startup_set = mode is not None
        saved.template = str(TEMPLATE)
        report["startup"] = mode
    else:
        report["startup"] = "already set" if saved.startup_set else "skipped"

    # The increment probe needs a project it is cheap and safe to save, so it is
    # only opportunistic here -- `Workspace.provision` settles it at the moment
    # it has the template open anyway.
    if prefs and not saved.inc_settled and _template_is_open(client):
        say("settling the save-increment preference (template is open)")
        inc = settle_increment_pref(client, say)
        saved.inc_settled = inc is not None
        report["inc"] = inc
    else:
        report["inc"] = ("already settled" if saved.inc_settled
                         else "deferred until the template is open")

    saved.applied = True
    saved.save()
    report["prefs"] = {"inc_settled": saved.inc_settled,
                       "startup_set": saved.startup_set}
    return report


def _template_is_open(client: TDClient) -> bool:
    """Is the open project the template? Then a save is instant and disposable."""
    try:
        from . import sync
        live = Path(sync.project_path(client))
    except Exception:
        return False
    return live.parent == TEMPLATE.parent and live.name.startswith(TEMPLATE.stem)


def settle_increment_now(client: TDClient, say=print) -> bool:
    """Settle the increment preference, if it is not already. Called by
    `provision` while the template is loaded, which is the cheap moment."""
    saved = Saved.load()
    if saved.inc_settled:
        return True
    if not saved.prefs:
        saved.prefs = read_prefs(
            client, [PREF_INC, PREF_STARTUP_MODE, PREF_STARTUP_FILE])
    inc = settle_increment_pref(client, say)
    saved.inc_settled = inc is not None
    saved.applied = True
    saved.save()
    _tidy_template_versions(say, client)
    return saved.inc_settled


# ---------------------------------------------------------------------- apply

def status(client: TDClient) -> dict:
    prefs = read_prefs(client, [PREF_INC, PREF_STARTUP_MODE, PREF_STARTUP_FILE])
    saved = Saved.load()
    ok, note = template_is_sane(client)
    folder = _run(client, "    return app.userPaletteFolder").strip()
    pal = Path(folder) / TOX.name if folder else None
    return {
        "prefs": prefs,
        "applied": saved.applied,
        "template": note,
        "template_ok": ok,
        "palette": str(pal) if pal and pal.exists() else "(not installed)",
    }


def apply(client: TDClient, say=print) -> dict:
    saved = Saved.load()
    if not saved.applied:
        saved.prefs = read_prefs(
            client, [PREF_INC, PREF_STARTUP_MODE, PREF_STARTUP_FILE])

    say("building the template project")
    _, original = make_template(client, say=say, reload_original=False)
    saved.template = str(TEMPLATE)

    # Probe now, while the template is the open project: it has one operator, so
    # a save is instant. The same probe against a real song project stalls for
    # one to three minutes per attempt because the Script TOP blocks the web
    # server thread.
    say("stopping the filename increment on save (measured on the template)")
    inc = settle_increment_pref(client, say)
    if inc is None:
        say("  ! could not confirm any value stops it; leaving the preference alone")
        write_prefs(client, {PREF_INC: saved.prefs.get(PREF_INC, 2)})
    else:
        say(f"  {PREF_INC} = {inc}")

    # the probe may have saved the template under an incremented name
    _tidy_template_versions(say, client)

    say("pointing TouchDesigner's startup file at it")
    mode = _settle_startup_mode(client, say)
    saved.palette_file = install_palette(client, say)

    say(f"reloading {original}")
    load_project(client, original)

    saved.applied = True
    saved.save()
    say(f"\nrecorded previous values in {STATE}")
    return {"inc": inc, "startup_mode": mode, "template": str(TEMPLATE)}


def _tidy_template_versions(say=print, client: TDClient | None = None) -> None:
    """Remove `_template.N.toe` files the increment probe may have produced.

    Never the one TouchDesigner currently has open: deleting the live project
    leaves TD pointing at a path that no longer exists, so the next save
    silently recreates a file nobody asked for.
    """
    live = ""
    if client is not None:
        try:
            from . import sync
            live = Path(sync.project_path(client)).name
        except Exception:
            live = ""
    for extra in sorted(TEMPLATE.parent.glob("_template.*.toe")):
        if extra.name == TEMPLATE.name or extra.name == live:
            continue
        extra.unlink()
        say(f"  removed probe artefact {extra.name}")


def _settle_startup_mode(client: TDClient, say=print) -> int | None:
    """Set the startup file, choosing the mode that TouchDesigner keeps.

    "Custom File" is one of three modes and the docs do not number them, so set
    the filename and try each mode, keeping the one that reads back with the
    filename still attached.
    """
    for candidate in (2, 1, 0):
        got = write_prefs(client, {PREF_STARTUP_MODE: candidate,
                                   PREF_STARTUP_FILE: str(TEMPLATE)})
        if got.get(PREF_STARTUP_MODE) == candidate and \
                got.get(PREF_STARTUP_FILE) == str(TEMPLATE):
            say(f"  {PREF_STARTUP_MODE} = {candidate}, file = {TEMPLATE}")
            return candidate
    say("  ! TouchDesigner did not accept a custom startup file")
    return None


def undo(client: TDClient, say=print) -> dict:
    saved = Saved.load()
    if not saved.applied:
        say("nothing recorded to undo")
        return {}
    if saved.prefs:
        got = write_prefs(client, saved.prefs)
        for k, v in saved.prefs.items():
            say(f"  {k} -> {v!r} (now {got.get(k)!r})")
    if saved.palette_file:
        p = Path(saved.palette_file)
        if p.exists():
            p.unlink()
            say(f"  removed {p}")
    say(f"  left {saved.template or TEMPLATE} in place (delete it by hand if unwanted)")
    saved.applied = False
    saved.save()
    return saved.prefs


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Configure the TouchDesigner install for lyricfield.")
    ap.add_argument("--status", action="store_true", help="report, change nothing")
    ap.add_argument("--undo", action="store_true", help="restore what was recorded")
    ap.add_argument("--make-template", action="store_true",
                    help="regenerate the template project only")
    ap.add_argument("--ensure", action="store_true",
                    help="make the environment ready (what every run does)")
    a = ap.parse_args(argv)

    client = TDClient()
    if not client.ping() and not a.ensure:
        print("TouchDesigner is not answering on :9988. Run with --ensure to "
              "start it, or open a project that has the td_mcp_server component.")
        return 1

    if a.status:
        for k, v in status(client).items():
            print(f"{k:12} {v}")
        return 0
    if a.undo:
        undo(client)
        return 0
    if a.make_template:
        make_template(client)
        return 0
    if a.ensure:
        for k, v in ensure(client).items():
            print(f"  {k}: {v}")
        return 0
    apply(client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
