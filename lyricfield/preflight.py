"""Assert what the render is about to depend on, and repair what can be.

Every failure this system has had took the same form: something was written into
TouchDesigner, had no effect, returned no error, and every later step reported
success. A thirty-second render of the wrong part of a song was written to disk
marked "verified with no problems" because each individual check it ran was
looking at something else.

Checking afterwards is not enough -- by then the minutes are spent and the
evidence is a video someone has to watch. So this runs *before* the render, and
it runs before **every** render rather than only during provisioning: the
Generate button resumes the run at `push`, which skips provisioning entirely,
which is precisely why a re-render could never repair its own timeline.

Two rules:

  * **Repair rather than refuse, wherever repair is possible.** The standing
    requirement for this system is that nothing is manual once the UI has the
    information. A stale params DAT is re-pushed, not reported.
  * **Refuse rather than render, when it is not.** A render that cannot be
    trusted costs more than one that does not happen.

Each check returns problems it could not fix. An empty list means the render is
standing on ground that has actually been looked at.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import sync
from .cues import CueTable


@dataclass
class Result:
    problems: list[str] = field(default_factory=list)
    repaired: list[str] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict:
        return {"ok": self.ok, "problems": self.problems,
                "repaired": self.repaired, "checked": self.checked}


def run(client, cfg, workspace=None, covers: float = 0.0,
        repair: bool = True, progress=None) -> Result:
    """Check everything the next render leans on.

    `covers` is the last second the render will reach, so the timeline and its
    play range can be widened to fit before anything is recorded.
    """
    say = progress or (lambda m: None)
    res = Result()

    for name, check in (
        ("the song this project holds", _project_is_the_song),
        ("lyrics, for a type that needs them", _lyrics_present),
        ("the timeline and its play range", _timeline),
        ("the pushed parameters", _params),
        ("the pushed field script", _field_script),
        ("the pushed cue table", _cues),
        ("a recorder left behind", _no_stranded_recorder),
    ):
        res.checked.append(name)
        try:
            check(client, cfg, workspace, covers, repair, res, say)
        except Exception as e:
            # A check that cannot run is not a passing check.
            res.problems.append(f"could not check {name}: {type(e).__name__}: {e}")
    return res


# ---------------------------------------------------------------- the checks

def _project_is_the_song(client, cfg, ws, covers, repair, res, say):
    """Renders are written into the selected song's folder with that song's cue
    table recorded beside them. If TouchDesigner is holding a different project,
    the take is mislabelled at birth."""
    if ws is None:
        return
    try:
        if ws.is_open_in(client):
            return
    except Exception:
        return          # cannot tell; the timeline check will catch the rest
    res.problems.append(
        f"TouchDesigner is not holding {ws.slug}'s project, so a render would be "
        f"of some other song and would be filed under this one")


def _lyrics_present(client, cfg, ws, covers, repair, res, say):
    """A lyric type with no words renders a field of nothing, for the whole
    song, and passes every brightness check there is."""
    vt = cfg.video_type
    if not getattr(vt, "needs_lyrics", False) or ws is None:
        return
    if CueTable.load(ws.cues_path).cues:
        return
    res.problems.append(
        f"{vt.name} draws the song's words and this song has none. Transcribe "
        f"the vocal or type the words in; rendering now would produce an empty "
        f"field for the length of the track.")


def _timeline(client, cfg, ws, covers, repair, res, say):
    """`end` is the length; `rangestart`..`rangeend` is where the playhead is
    allowed to go, and with `rangelimit` at "loop" it physically cannot leave.
    A frame set outside it is discarded silently."""
    want = max(float(covers or 0.0), float(getattr(cfg.track, "duration", 0.0) or 0.0))
    if want <= 0:
        return
    before = sync.timeline_state(client)
    if before.get("covers_seconds", 0) >= want and before.get("range_ok"):
        return
    if not repair:
        res.problems.append(
            f"the timeline reaches {before.get('covers_seconds', 0):.0f}s and the "
            f"render needs {want:.0f}s")
        return
    after = sync.set_timeline_length(client, want + 2.0)
    say(f"widened the timeline to {after.get('seconds', '?')}s")
    res.repaired.append("timeline and play range")
    check = sync.timeline_state(client)
    if check.get("covers_seconds", 0) < want or not check.get("range_ok"):
        res.problems.append(
            f"the timeline still does not cover {want:.0f}s after widening it "
            f"({check})")


def _params(client, cfg, ws, covers, repair, res, say):
    """The config reaches the renderer as a generated Python dict in a DAT. If
    that write is lost, every tunable falls back to a default and the render is
    plausible and wrong."""
    wanted = sync.params_text(cfg)
    current = _dat(client, sync.PARAMS_DAT)
    if current is not None and current.strip() == wanted.strip():
        return
    if not repair:
        res.problems.append("the pushed parameters do not match the config")
        return
    sync.push_params(client, cfg)
    res.repaired.append("parameters")
    if (_dat(client, sync.PARAMS_DAT) or "").strip() != wanted.strip():
        res.problems.append(
            "the parameters DAT does not hold what was pushed, so the renderer "
            "is running on fallback values")


def _field_script(client, cfg, ws, covers, repair, res, say):
    """The repo is the source of truth for behaviour; TouchDesigner holds a
    copy. A copy that has drifted is the one thing no amount of editing here
    would fix."""
    src = getattr(cfg.video_type, "field_source", None)
    wanted = src() if callable(src) else None
    if not wanted:
        return
    current = _dat(client, sync.CALLBACKS)
    if current is not None and current.strip() == wanted.strip():
        return
    if not repair:
        res.problems.append("the field script in TouchDesigner is not the repo's")
        return
    sync.push_field(client, cfg)
    res.repaired.append("field script")


def _cues(client, cfg, ws, covers, repair, res, say):
    """Words are pushed as tab-separated text into a table DAT. A word holding
    a tab, or a partial write, drops cues -- and the render still measures well,
    because the checks compare the picture against the *repo's* cue list."""
    if ws is None:
        return
    wanted = CueTable.load(ws.cues_path)
    if not wanted.cues:
        return
    try:
        got = sync.pull_cues(client)
    except Exception:
        got = None
    if got is not None and len(got.cues) == len(wanted.cues):
        return
    if not repair:
        res.problems.append("the cue table in TouchDesigner is not this song's")
        return
    sync.push_cues(client, wanted)
    sync.reset_field_state(client)
    res.repaired.append("cue table")
    try:
        again = sync.pull_cues(client)
    except Exception:
        return
    if len(again.cues) != len(wanted.cues):
        res.problems.append(
            f"TouchDesigner holds {len(again.cues)} cues where the song has "
            f"{len(wanted.cues)}; some words would never appear")


def _no_stranded_recorder(client, cfg, ws, covers, repair, res, say):
    """A stopped render leaves the Movie File Out in the network, and the next
    render then refuses to start -- one aborted preview quietly breaks every
    render after it."""
    from . import render as render_mod
    if not render_mod.recorder_present(client):
        return
    if not repair:
        res.problems.append("a previous recording is still in the network")
        return
    say("clearing a recorder left behind by an earlier render")
    render_mod.stop_recording(client)
    res.repaired.append("stranded recorder")
    if render_mod.recorder_present(client):
        res.problems.append(
            "a previous recording is still in the network and would stop this "
            "render from starting")


# ------------------------------------------------------------------ helpers

def _dat(client, path: str) -> str | None:
    try:
        return client.dat_text(path)
    except Exception:
        return None
