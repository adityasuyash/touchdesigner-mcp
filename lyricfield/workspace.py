"""One self-contained folder per song.

    <root>/<song-slug>/
        project.toe        this song's TouchDesigner project
        config.toml        this song's tunables + measured track facts
        cues.tsv           this song's cue table
        source/            the original audio
        stems/             vocals.wav, no_vocals.wav
        exports/           renders, and exports/stills/

Everything a song needs travels together, so a finished piece can be archived or
handed over as a single directory.

On creating the project file: rather than keeping a template .toe in the repo
(binary, undiffable, and immediately stale), a new song's project is forked from
whatever TouchDesigner currently has open, via `project.save(<new path>)`. The
live project is the template. `sync.push_all` then loads this song's script,
params and cues into it.

The constraint to remember is that TouchDesigner holds exactly one project open,
and the MCP server lives *inside* that project. Switching songs means opening a
different .toe by hand; the connection drops with the old one and returns with
the new. `Workspace.is_open_in` checks which project TD actually has loaded, so
a push can refuse to write a song's data into the wrong project.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import types as types_mod
from .config import Config
from .cues import CueTable
from .styles import Style, get_style

DEFAULT_ROOT = Path.home() / "lyricfield-projects"
# A project containing only the MCP server, used as the starting point for a new
# song. Created by lyricfield.td_setup; see sync.load_project for why loading
# anything without a server in it is unrecoverable.
DEFAULT_TEMPLATE = DEFAULT_ROOT / "_template.toe"

_DASHES = re.compile(r"-+")


def slugify(name: str) -> str:
    """A folder name for a song title, in any script.

    This used to strip everything outside `[a-z0-9]` and fall back to the
    literal string "untitled". Every Devanagari, CJK, Cyrillic or Arabic title
    therefore produced the *same* slug, and the run's workspace stage opens an
    existing folder by slug -- so the second such song adopted the first one's
    folder, found its cue table, reported "keeping existing cue table", and
    rendered one song's video with another song's lyrics. Marked verified.

    Unicode letters and digits are kept, which every filesystem this runs on
    accepts. A title with no alphanumerics at all (punctuation, emoji) falls
    back to a hash of the title rather than a shared constant: two such songs
    must still not collide.
    """
    kept = "".join(ch if ch.isalnum() else "-" for ch in name.strip().lower())
    slug = _DASHES.sub("-", kept).strip("-")
    if slug:
        return slug
    return "song-" + hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]


def distinct_slug(name: str, root: Path,
                  belongs: Callable[[Path], bool]) -> str:
    """`slugify(name)`, or a variant of it that is not already another song's.

    Titles that differ only in punctuation slug identically ("Song #1" and
    "Song 1"), and a slug collision silently merges two songs' data. When the
    folder that already holds this slug is a different song, take the next free
    variant instead of moving in with it.
    """
    base = slugify(name)
    candidate, n = base, 2
    while True:
        d = Path(root).expanduser() / candidate
        if not d.exists() or belongs(d):
            return candidate
        candidate = f"{base}-{n}"
        n += 1


@dataclass
class Workspace:
    root: Path
    slug: str
    name: str = ""

    # ---------- paths ----------

    @property
    def dir(self) -> Path:
        return self.root / self.slug

    @property
    def project(self) -> Path:
        return self.dir / "project.toe"

    @property
    def config_path(self) -> Path:
        return self.dir / "config.toml"

    @property
    def cues_path(self) -> Path:
        return self.dir / "cues.tsv"

    @property
    def drums_path(self) -> Path:
        """When each drum is struck. A sidecar rather than a config field:
        a busy track has hundreds of hits, and they do not belong in a TOML the
        UI rewrites on every edit."""
        return self.dir / "drums.tsv"

    @property
    def source_dir(self) -> Path:
        return self.dir / "source"

    @property
    def stems_dir(self) -> Path:
        return self.dir / "stems"

    @property
    def exports_dir(self) -> Path:
        return self.dir / "exports"

    @property
    def stills_dir(self) -> Path:
        return self.exports_dir / "stills"

    def export_path(self, suffix: str = "", ext: str = "mp4") -> Path:
        """Next free export name: <slug>.mp4, <slug>_002.mp4, ... so a re-render
        never silently overwrites the take you were comparing against."""
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{self.slug}{('_' + suffix) if suffix else ''}"
        candidate = self.exports_dir / f"{stem}.{ext}"
        n = 2
        while candidate.exists():
            candidate = self.exports_dir / f"{stem}_{n:03d}.{ext}"
            n += 1
        return candidate

    # ---------- takes ----------

    def write_take(self, export: Path, ready: bool = False) -> Path:
        """Record what produced an export, beside it.

        `export_path` versions the filename but not the settings, so a take
        could not be identified, compared or returned to. The config and cues
        are small text files with serialisers already, which makes a take a
        thing the system can act on rather than just a file someone kept.
        """
        export = Path(export)
        self.load_config().save(export.with_suffix(".toml"))
        CueTable.load(self.cues_path).save(export.with_suffix(".tsv"))
        if ready:
            export.with_suffix(".ready").write_text("verified with no problems\n")
        return export.with_suffix(".toml")

    def takes(self) -> list[dict]:
        """Every export that has its settings recorded, newest first."""
        out = []
        if not self.exports_dir.exists():
            return out
        for mp4 in sorted(self.exports_dir.glob("*.mp4")):
            settings = mp4.with_suffix(".toml")
            out.append({
                "name": mp4.stem,
                "file": mp4.name,
                "when": mp4.stat().st_mtime,
                "size_mb": round(mp4.stat().st_size / 1048576, 1),
                "has_settings": settings.exists(),
                "ready": mp4.with_suffix(".ready").exists(),
            })
        return sorted(out, key=lambda t: -t["when"])

    def restore_take(self, name: str) -> Config:
        """Put a take's settings back as the working copy."""
        cfg_file = self.exports_dir / f"{name}.toml"
        cues_file = self.exports_dir / f"{name}.tsv"
        if not cfg_file.exists():
            raise FileNotFoundError(f"take {name!r} has no recorded settings")
        cfg = Config.load(cfg_file)
        cfg.save(self.config_path)
        if cues_file.exists():
            CueTable.load(cues_file).save(self.cues_path)
        return cfg

    # ---------- lifecycle ----------

    def _adopt(self, path: str | Path, copy: bool = True) -> Path:
        """Take a user-supplied file into the song folder, if it is there."""
        src = Path(path).expanduser()
        if copy and src.exists():
            dst = self.source_dir / src.name
            if not dst.exists():
                shutil.copy2(src, dst)
            return dst
        return src

    @classmethod
    def create(cls, name: str, source_audio: str | Path | None = None,
               root: str | Path = DEFAULT_ROOT,
               video_type: str | None = None,
               style: str | Style | None = None,
               copy_source: bool = True,
               slug: str | None = None,
               plate: str | Path | None = None) -> "Workspace":
        # `slug` is passed when the caller has already resolved a collision --
        # two songs whose titles slug the same must not share a folder.
        ws = cls(root=Path(root).expanduser(), slug=slug or slugify(name), name=name)
        for d in (ws.dir, ws.source_dir, ws.stems_dir, ws.exports_dir, ws.stills_dir):
            d.mkdir(parents=True, exist_ok=True)

        # A style carries its own video type, and it wins: picking "calm drift"
        # is picking the renderer it was made for.
        st = None
        if style is not None:
            st = style if isinstance(style, Style) else get_style(style)
            video_type = st.type
        cfg = Config(type=video_type or types_mod.DEFAULT_TYPE)
        if st is not None:
            cfg = st.apply_to(cfg)
            cfg.track.style = st.slug

        if source_audio:
            cfg.track.source = str(ws._adopt(source_audio, copy_source))
        if plate:
            # Footage the lyrics are lettered over. Copied in beside the audio
            # for the same reason: a song folder that depends on a file
            # somewhere else in the filesystem stops rendering the day that
            # file moves.
            cfg.track.plate = str(ws._adopt(plate, copy_source))

        if not ws.config_path.exists():
            cfg.save(ws.config_path)
        if not ws.cues_path.exists():
            CueTable().save(ws.cues_path)
        return ws

    @classmethod
    def open(cls, slug: str, root: str | Path = DEFAULT_ROOT) -> "Workspace":
        ws = cls(root=Path(root).expanduser(), slug=slug, name=slug)
        if not ws.dir.exists():
            raise FileNotFoundError(f"no workspace {slug!r} under {ws.root}")
        cfg = Config.load(ws.config_path)
        ws.name = cfg.track.title or slug
        return ws

    # ---------- state ----------

    def load_config(self) -> Config:
        return Config.load(self.config_path)

    def save_config(self, cfg: Config) -> None:
        cfg.save(self.config_path)

    def load_cues(self) -> CueTable:
        return CueTable.load(self.cues_path)

    def set_type(self, slug: str) -> Config:
        """Switch this song to a different renderer, keeping every measured fact.

        The type's tunables reset to its defaults rather than carrying over --
        they describe a different visual system, and a number that means "grid
        columns" in one means nothing in the next.
        """
        cfg = self.load_config().with_type(slug)
        cfg.track.style = ""
        self.save_config(cfg)
        return cfg

    # ---------- touchdesigner ----------

    def fork_project_from_current(self, client, timeout: float = 420.0) -> Path:
        """Save whatever TD currently has open into this workspace as project.toe.

        This is how a new song gets its project: the live network becomes the
        template. TD keeps working on the *new* file afterwards, which is what
        you want -- you are now editing this song.
        """
        from . import sync
        sync.quiesce(client)
        target = str(self.project)
        try:
            client.run(
                f"project.save({target!r})\nprint(project.name)",
                timeout=timeout,
            )
        except Exception:
            # TD routinely stops answering mid-save and finishes anyway
            if not client.wait_until_ready(seconds=timeout):
                raise
        if not self.project.exists():
            raise RuntimeError(
                f"TD reported saving but {self.project} does not exist. "
                "Check the path is writable."
            )
        return self.project

    def provision(self, client, progress=None, template: Path | None = None,
                  rebuild: bool = False) -> dict:
        """Make TouchDesigner hold this song's project, built and verified.

        This is the step that used to be a person opening a .toe and dragging
        components around. It is safe to run every time: if the project already
        exists it is opened rather than recreated, and building is idempotent.

        A damaged or half-built project is therefore not a rescue operation --
        `verify()` notices and `build()` puts it back, from `config.toml` and
        `cues.tsv`, which are the actual source of truth.
        """
        from . import sync
        from .cues import CueTable

        say = progress or (lambda m: None)
        cfg = self.load_config()
        vt = cfg.video_type
        out: dict = {"song": self.slug, "type": cfg.type}

        # ---- 1. the right project open ----
        # `is_open_in` rather than an exact filename match: until the increment
        # preference is off, TouchDesigner's live name drifts to project.N.toe
        # and an exact comparison would reload the project on every run.
        if not self.is_open_in(client):
            if self.project.exists():
                say(f"opening {self.project.name}")
                sync.load_project(client, self.project)
            else:
                src = Path(template) if template else DEFAULT_TEMPLATE
                if not src.exists():
                    raise FileNotFoundError(
                        f"no template at {src}; run environment setup first so a "
                        "project containing the MCP server exists to start from"
                    )
                say(f"creating {self.project.name} from the template")
                sync.load_project(client, src)
                # The template is open and nearly empty, so a save is instant and
                # the file is disposable -- the one cheap, safe moment to settle
                # whether TouchDesigner renames a project when it saves. Doing it
                # here also means the save below lands on the name we asked for.
                from . import td_setup
                try:
                    td_setup.settle_increment_now(client, say)
                except Exception as e:
                    say(f"could not settle the save-increment preference: {e}")
                self.dir.mkdir(parents=True, exist_ok=True)
                sync.save_project_as(client, self.project)
            out["opened"] = str(self.project)
        else:
            out["opened"] = "already open"

        # ---- 2. the network ----
        # Composed: the words in `/project1/words`, whatever is behind them in
        # `/project1/beat`, and `/project1/out` the mix of the two. One layout
        # whether or not there is a layer, because two layouts means two code
        # paths and the one that is rarely taken is the one that rots.
        if vt.can_build:
            from . import compose
            say(f"building {vt.name} with the beat response")
            res = compose.build(client, cfg, progress=say)
            out["built"] = 1
            out["problems"] = res.get("problems")
            out["words"] = res.get("words")
            out["discrepancies"] = []
        else:
            say(f"{vt.name} has no builder; leaving the network as found")
            out["built"] = None

        # ---- 2b. the timeline has to be at least as long as the song ----
        # The template carries whatever length the project it came from had --
        # 94s, from the 90s benchmark track. A 264s song in a 94s timeline
        # cannot play or render past the loop point, and nothing says so.
        # `exact`: this is the one place that knows how long the song really is,
        # so it sets the length rather than only raising it. Otherwise a project
        # forked from a longer song, or stretched by an earlier render, keeps a
        # timeline that has nothing to do with the track in it.
        if cfg.track.duration:
            want = cfg.track.duration + 4.0
            out["timeline"] = sync.set_timeline_length(client, want, exact=True)
            say(f"timeline set to {want:.0f}s")

        # ---- 3. content ----
        # Cues only for a renderer that draws them -- pushing words to a
        # beatsync type leaves another renderer's lyrics in the project for this
        # one to ignore, which is the rule `run._push` states and this did not
        # follow. And the drums, which every renderer reads and which this never
        # pushed at all, so a song provisioned here had no beat to answer.
        wants_words = cfg.video_type.needs_lyrics
        cues = CueTable.load(self.cues_path) if wants_words else None
        drums = None
        if self.drums_path.exists():
            from .drums import DrumTable
            drums = DrumTable.load(self.drums_path)
        say("pushing params, field script"
            + (", cues" if wants_words else "")
            + (", drums" if drums is not None else ""))
        out["pushed"] = sync.push_composed(client, cfg, cues, drums)

        # ---- 4. persist ----
        # A built network that is only in TouchDesigner's memory is one crash
        # away from gone. Rebuilding would recover it, but nothing should have
        # to.
        if out.get("built"):
            say("saving the project")
            out["saved"] = sync.save_project(client)
        return out

    def live_project_in(self, client) -> Path | None:
        """The .toe TouchDesigner actually has open, or None if it cannot say."""
        try:
            out = client.run(
                "def main():\n"
                "    import os\n"
                "    return os.path.join(project.folder, project.name)\n"
                "print(main())"
            ).strip()
        except Exception:
            return None
        return Path(out) if out else None

    def is_open_in(self, client) -> bool:
        """Is TouchDesigner actually running this workspace's project?

        This is the guard that stops a push landing in the wrong song, so it has
        to be right in both directions: too strict and every push is refused,
        too loose and a song's data lands in another song's project.

        With `lyricfield.td_setup` applied the filename is stable and an exact
        match is correct. Without it TouchDesigner renames the project on every
        save -- project.toe, then project.1.toe, then project.2.toe -- and an
        exact comparison would report "wrong project" forever. Hence the
        fallback: any project*.toe in this workspace's folder is this song.
        """
        live = self.live_project_in(client)
        if live is None:
            return False
        try:
            if live.resolve() == self.project.resolve():
                return True
            return (live.parent.resolve() == self.dir.resolve()
                    and live.name.startswith("project") and live.suffix == ".toe")
        except OSError:
            return False

    def to_dict(self) -> dict:
        cfg = self.load_config() if self.config_path.exists() else Config()
        cues = self.load_cues() if self.cues_path.exists() else CueTable()
        exports = sorted(p.name for p in self.exports_dir.glob("*.mp4")) \
            if self.exports_dir.exists() else []
        return {
            "slug": self.slug,
            "name": self.name,
            "dir": str(self.dir),
            "has_project": self.project.exists(),
            "cues": len(cues.cues),
            "lines": len(cues.lines),
            "duration": cfg.track.duration,
            "type": cfg.type,
            "style": getattr(cfg.track, "style", ""),
            "exports": exports,
            # When this song was last worked on, so the sidebar can lead with
            # what you were doing rather than with the alphabet.
            "touched": self._touched(),
            # What is missing, named. A half-ingested song showed a blank
            # where its word count goes and was otherwise indistinguishable
            # from a finished one -- you found out by picking it.
            "stage": self._stage(cfg, cues, exports),
        }

    def _touched(self) -> float:
        newest = 0.0
        for p in (self.config_path, self.cues_path, self.exports_dir):
            try:
                newest = max(newest, p.stat().st_mtime)
            except OSError:
                pass
        return round(newest, 3)

    def _stage(self, cfg, cues, exports) -> str:
        """How far this song got, as one word the sidebar can show."""
        if not (cfg.track.source or self.source_dir.exists()):
            return "empty"
        if not cfg.track.duration:
            return "not analysed"
        if cfg.video_type.needs_lyrics and not cues.cues:
            return "no words"
        if exports:
            return "rendered"
        return "ready"


def list_workspaces(root: str | Path = DEFAULT_ROOT) -> list[Workspace]:
    root = Path(root).expanduser()
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if (d / "config.toml").exists():
            out.append(Workspace(root=root, slug=d.name, name=d.name))
    return out
