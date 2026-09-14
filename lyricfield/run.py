"""The whole job, as ordered stages: song details in, finished preview out.

Every step that used to be a button a person pressed in the right order is a
stage here, and each one knows whether it is already done. Re-running resumes
rather than repeats, which matters because the slow parts are very slow --
separation takes minutes and transcription costs money.

    environment -> workspace -> ingest -> provision -> push -> preview -> verify

Two rules shape the error handling:

  * **Retry the transient, stop at the rest.** TouchDesigner stalls for one to
    three minutes on save as a matter of course, and Groq returns 503s. Those
    are worth another attempt. A failed stage stops the run with everything
    before it intact.
  * **Never continue past a failure.** Rendering from a stale cue table or an
    unbuilt network produces something that looks like output and is not, which
    is worse than stopping.

The full-length render is deliberately *not* a stage. The automatic run produces
a short preview and measures it; committing to a long render is a separate act.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .td_client import TDUnavailable

PENDING, RUNNING, DONE, FAILED, SKIPPED, STOPPED = (
    "pending", "running", "done", "failed", "skipped", "stopped")


class Stopped(Exception):
    """Raised when a run is asked to stop. Not a failure -- everything already
    finished stays finished, and the run can be resumed from here."""

# How long a preview runs. Long enough to show drift, dissolve and a few cues;
# short enough that judging a look does not cost a full render.
PREVIEW_SECONDS = 8.0


@dataclass
class Stage:
    key: str
    title: str
    state: str = PENDING
    message: str = ""
    detail: dict = field(default_factory=dict)
    seconds: float = 0.0
    # 0..1 while this stage is running, when it can say. Only the render knows
    # its own progress -- it counts frames written -- and without it the UI
    # could only fill a bar by counting finished stages, which does not move at
    # all through the one step that takes minutes.
    fraction: float | None = None
    started: float = 0.0


@dataclass
class Run:
    id: str
    song: str
    stages: list[Stage]
    state: str = PENDING
    log: list[str] = field(default_factory=list)
    # Problems reported by any stage, not only the one that measures the output.
    # A problem means the render cannot be trusted; a warning means the material
    # is imperfect -- a transcription that missed a line -- which is worth
    # showing and does not make the render wrong.
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    error: str = ""
    started: float = 0.0
    finished: float = 0.0

    def stage(self, key: str) -> Stage | None:
        return next((s for s in self.stages if s.key == key), None)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["elapsed"] = round((self.finished or time.time()) - self.started, 1)
        return d


# --------------------------------------------------------------------- context

@dataclass
class Ctx:
    """Everything the stages share. The workspace is bound once, at submit time.

    That binding matters: the previous job model read the selected song from a
    global when each step ran, so choosing a different song mid-run redirected
    that run's writes into the new song's folder.
    """
    client: object
    name: str = ""
    source: str = ""
    video_type: str | None = None
    back_type: str | None = None
    back_style: str | None = None
    style: str | None = None
    workspace: object = None
    options: dict = field(default_factory=dict)
    run: object = None          # set by execute(); `verify` reads the preview path
    # The cancel signal. It lives here rather than on `Run` because `Run.to_dict`
    # uses `asdict`, and an Event is not serialisable.
    stop: object = field(default_factory=threading.Event)

    def should_stop(self) -> bool:
        return self.stop.is_set()

    def check(self) -> None:
        if self.stop.is_set():
            raise Stopped()

    @property
    def cfg(self):
        return self.workspace.load_config()


# ---------------------------------------------------------------------- retry

def attempt(fn, say, tries: int = 3, delay: float = 5.0,
            transient=(TDUnavailable,)):
    """Run `fn`, retrying only the failures that are worth retrying."""
    last = None
    for i in range(1, tries + 1):
        try:
            return fn()
        except transient as e:
            last = e
            if i < tries:
                say(f"{type(e).__name__}: {e} — retry {i}/{tries - 1} in {delay:.0f}s")
                time.sleep(delay)
    raise last


# --------------------------------------------------------------------- stages

def _environment(ctx: Ctx, say) -> dict:
    from . import td_setup
    return td_setup.ensure(ctx.client, say=say)


def _workspace(ctx: Ctx, say) -> dict:
    from .config import Config
    from .workspace import DEFAULT_ROOT, Workspace, distinct_slug, slugify

    def belongs(folder: Path) -> bool:
        """Is this folder already holding *this* song?

        Reusing a folder is the normal, wanted case -- it is what makes a run
        resumable. Reusing another song's folder is the disaster: ingest finds
        its cue table, reports "keeping existing cue table", and renders one
        song's words over another song's audio. So compare the source before
        moving in.
        """
        cfg_path = folder / "config.toml"
        if not cfg_path.exists():
            return True                      # nothing there to conflict with
        if not ctx.source:
            return True                      # nothing to compare it against
        try:
            recorded = Path(Config.load(cfg_path).track.source or "").name
        except Exception:
            return True
        return not recorded or recorded == Path(ctx.source).name

    slug = distinct_slug(ctx.name, DEFAULT_ROOT, belongs)
    if slug != slugify(ctx.name):
        say(f"{slugify(ctx.name)!r} already belongs to another song; using {slug!r}")
    try:
        ctx.workspace = Workspace.open(slug)
        say(f"using existing song {slug}")
    except FileNotFoundError:
        ctx.workspace = Workspace.create(
            ctx.name, ctx.source or None,
            video_type=ctx.video_type, style=ctx.style, slug=slug)
        say(f"created {slug}")
    cfg = ctx.workspace.load_config()
    if not cfg.track.title:
        cfg.track.title = ctx.name
        ctx.workspace.save_config(cfg)
    out = ctx.workspace.to_dict()
    out.update(_honour_pick(ctx, say))
    return out


def _honour_pick(ctx: Ctx, say) -> dict:
    """Make an existing song wear the renderer and look that were picked.

    `Workspace.create` honours both, so a *new* song was always right. An
    existing one ignored them entirely: the gallery would show a beatsync look
    selected, the run would report success, and what came out was whatever
    renderer the song was made with the first time. Same defect class as the UI
    not sending the type at all -- the choice is accepted, acknowledged and
    discarded -- so it is fixed at the stage that owns the config rather than in
    the caller.

    Provision re-verifies the network against the type it finds here and
    rebuilds when they disagree, and push reads the type's field script, so
    changing it at this point is enough to change the whole run.
    """
    from .styles import get_style

    ws, cfg = ctx.workspace, ctx.workspace.load_config()
    want_type, changed = ctx.video_type or "", {}

    # A style carries its own type and it wins, exactly as it does on create.
    st = None
    if ctx.style:
        try:
            st = get_style(ctx.style)
        except (KeyError, FileNotFoundError) as e:
            say(f"no style {ctx.style!r}: {e}")
        else:
            want_type = st.type

    if want_type and want_type != cfg.type:
        try:
            cfg = ws.set_type(want_type)
        except KeyError:
            say(f"no video type {want_type!r}; staying on {cfg.type}")
        else:
            say(f"switched to {cfg.video_type.name}")
            changed["type"] = cfg.type

    if st is not None and cfg.track.style != st.slug:
        cfg = st.apply_to(cfg)
        cfg.track.style = st.slug
        ws.save_config(cfg)
        say(f"applied the {st.name} look")
        changed["style"] = st.slug

    # What sits behind the words, applied last so it overrides whatever the
    # style brought with it -- the style is the word look, this is the choice
    # made on top of it.
    if ctx.back_type is not None or ctx.back_style is not None:
        if _apply_backdrop(cfg, ctx.back_type or "", ctx.back_style or "", say):
            ws.save_config(cfg)
            changed["backdrop"] = f"{ctx.back_type or 'none'}/{ctx.back_style or ''}"
    return changed


def _apply_backdrop(cfg, back_type: str, back_style: str, say) -> bool:
    """Put a beatsync look behind the words.

    The choice is a (renderer, style) pair rather than a preset key, because the
    thing being chosen is one of the looks already on screen -- inventing a
    parallel vocabulary for them was the mistake this replaces.

    Nothing forbids *reading* a style of another type; only `Style.apply_to`
    refuses to apply one across types, and that refusal is right. This
    translates instead.
    """
    from .styles import get_style
    from .types import get_type

    mod = cfg.video_type._params_module()
    translate = getattr(mod, "backdrop_from", None)
    if translate is None:
        say(f"{cfg.video_type.name} cannot carry anything behind it")
        return False

    cfg.track.back_type = back_type
    cfg.track.back_style = back_style
    if not back_type:
        translate(cfg.params, None)
        say("nothing behind the words")
        return True

    try:
        vt = get_type(back_type)
    except KeyError:
        say(f"no video type {back_type!r}; leaving the backdrop alone")
        return False
    source = vt.default_params()
    if back_style:
        try:
            source = get_style(back_style, type=back_type).params
        except (KeyError, FileNotFoundError) as e:
            say(f"no {back_type} style {back_style!r}: {e}")
            return False

    clamped = translate(cfg.params, source)
    mod.reconcile(cfg.params)
    problems = cfg.params.validate()
    if problems:
        say(f"that backdrop does not fit this look: {'; '.join(problems)}")
        return False
    # `reconcile` runs before `validate`, so a backdrop can never fail -- it is
    # quietly clipped instead. Say what had to give, or a look renders at half
    # strength and nothing reports it.
    for line in clamped:
        say(line)
    for note in getattr(cfg.params, "notes", list)():
        say(note)
    say(f"put {back_style or vt.name} behind the words")
    return True


def _ingest(ctx: Ctx, say) -> dict:
    from . import pipeline
    from .cues import CueTable

    ws = ctx.workspace
    cfg = ws.load_config()
    vt = cfg.video_type
    source = ctx.source or cfg.track.source
    if not source:
        raise ValueError("no source audio for this song")

    say(f"{vt.name} is a {vt.family} type; it needs {', '.join(sorted(vt.needs))}")
    res = pipeline.prepare(
        source, ws.config_path, ws.cues_path, ws.drums_path,
        stem_root=ws.stems_dir,
        needs=vt.needs,
        groq_key=ctx.options.get("api_key"),
        language=ctx.options.get("language"),
        prompt=ctx.options.get("prompt"),
        force_separate=bool(ctx.options.get("force_separate")),
        force_transcribe=bool(ctx.options.get("force_transcribe")),
        should_stop=ctx.should_stop,
        progress=say)

    # A lyric video with no words would build a project that renders an empty
    # field. Stop here and say so rather than producing convincing nothing.
    table = CueTable.load(ws.cues_path)
    if vt.needs_lyrics and not table.cues:
        raise ValueError(
            f"{vt.name} is a lyric type but this song has no cue table. "
            "Transcribe the vocal, or type the words in, before rendering.")

    # Say what happened rather than leaving it to a state word. "reused" and
    # "did not run" look identical otherwise, which is what made this look
    # like transcription had failed when it had just produced 380 words.
    reused = [x.split(" (")[0] for x in res.skipped]
    parts = []
    if res.duration:
        parts.append(f"{res.duration:.0f}s track")
    if table.cues:
        parts.append(f"{len(table.cues)} words across {len(table.lines)} lines")
    if reused:
        parts.append("reused " + ", ".join(reused))
    say(" · ".join(parts) or "prepared")
    return res.to_dict()


def _provision(ctx: Ctx, say) -> dict:
    return attempt(lambda: ctx.workspace.provision(ctx.client, progress=say), say)


def _describe(ctx: Ctx, say) -> dict:
    """Turn a written description into settings, before anything is pushed.

    It sits between provision and push so the preview that follows is the
    described look -- there is no point proposing settings the render will not
    use. Nothing is kept: the config is saved for this preview, and the take is
    what the person accepts or rejects.
    """
    text = (ctx.options.get("describe") or "").strip()
    if not text:
        return {"stage_skipped": True, "why": "nothing described"}
    from . import describe as describe_mod
    cfg = ctx.workspace.load_config()
    say(f"asking for settings matching {text!r}")
    prop = describe_mod.propose(cfg, text)
    if prop.problems:
        # Refuse rather than render something known-broken, and say which part.
        raise ValueError("the proposed settings are not valid: "
                         + "; ".join(prop.problems))
    cfg.save(ctx.workspace.config_path)
    if prop.why:
        say(prop.why)
    say(f"{len(prop.changed)} settings changed")
    for line in prop.ignored:
        say(f"ignored — {line}")
    return prop.to_dict()


def _push(ctx: Ctx, say) -> dict:
    from . import sync
    from .cues import CueTable
    ws = ctx.workspace
    cfg = ws.load_config()
    problems = cfg.validate()
    if problems:
        raise ValueError("config is not valid: " + "; ".join(problems))
    # A type that needs no lyrics gets no cue table: pushing one would leave
    # another renderer's words in the project for this one to ignore.
    table = CueTable.load(ws.cues_path) if cfg.video_type.needs_lyrics else None
    # Every renderer answers the drums, words or not, so this goes in always.
    from .drums import DrumTable
    drums = DrumTable.load(ws.drums_path)
    done = attempt(lambda: sync.push_all(ctx.client, cfg, table, drums), say)
    return {"pushed": done}


def preview_window(cfg, cues, seconds: float) -> float:
    """Where to start a preview so it contains something worth looking at.

    A preview from t=0 shows whatever the song opens with, which is often an
    intro: august's first word lands at 6.6s, so eight seconds from zero held
    two cues against nineteen for the benchmark track.

    Rather than guess from the kick or the first word -- both of which picked a
    worse window than zero on one song or the other -- slide the window over the
    cue table and take the densest one. Ties go to the earliest, so a song that
    is uniformly busy still previews from near its start.
    """
    if not cues:
        return 0.0
    times = sorted(c.start for c in cues)
    dur = float(getattr(cfg.track, "duration", 0.0) or 0.0)
    limit = max(0.0, dur - seconds) if dur else None

    # A sliding count rather than a rescan per candidate. The nested version
    # cost seconds on a wordy ten-minute track, on every run and every config
    # load, for a number that never changes.
    import bisect

    best_at, best_n = 0.0, bisect.bisect_left(times, seconds)
    for t in times:
        at = max(0.0, t - 0.75)          # open just before a word, not on it
        if limit is not None:
            at = min(at, limit)
        n = bisect.bisect_left(times, at + seconds) - bisect.bisect_left(times, at)
        if n > best_n:
            best_at, best_n = at, n
    return round(best_at, 2)


def _preview(ctx: Ctx, say) -> dict:
    from . import render as render_mod
    from .cues import CueTable
    ws, cfg = ctx.workspace, ctx.workspace.load_config()
    # Length is a choice at generate time: the short preview, the whole track,
    # or a specific number of seconds.
    if ctx.options.get("length") == "full" and cfg.track.duration:
        seconds = float(cfg.track.duration)
        out = ws.export_path()
        say(f"rendering the full {seconds:.0f}s")
    else:
        seconds = float(ctx.options.get("preview_seconds") or PREVIEW_SECONDS)
        out = ws.export_path("preview")
    # An explicit start wins; left empty, pick the most lyric-dense window.
    # Either way the choice is reported, because a render of a part of the song
    # nobody asked for looks exactly like a bug.
    chosen = ctx.options.get("start_seconds")
    if ctx.options.get("length") == "full":
        start, why = 0.0, "the whole track"
    elif chosen not in (None, ""):
        start, why = max(0.0, float(chosen)), "as asked"
    else:
        start = preview_window(cfg, CueTable.load(ws.cues_path).cues, seconds)
        why = "the busiest stretch"
    dur = float(getattr(cfg.track, "duration", 0.0) or 0.0)
    if dur:
        start = min(start, max(0.0, dur - seconds))
        # A preview longer than the song records silence past the end and then
        # muxes full-length audio against it.
        seconds = min(seconds, max(1.0, dur - start))
    say(f"{seconds:.0f}s from {int(start//60)}:{int(start%60):02d} ({why})")

    # Check what the render is about to lean on, and repair what can be
    # repaired. This runs here rather than only in provisioning because the
    # Generate button resumes at `push`, skipping provisioning entirely -- which
    # is why a re-render could never fix its own timeline.
    from . import preflight
    pre = preflight.run(ctx.client, cfg, ws, covers=start + seconds + 3.0,
                        progress=say)
    for what in pre.repaired:
        say(f"repaired {what}")
    if not pre.ok:
        raise ValueError("not ready to render: " + "; ".join(pre.problems))
    res = attempt(lambda: render_mod.render(
        ctx.client, out, seconds,
        vocals=cfg.track.vocals or None,
        instrumental=cfg.track.instrumental or None,
        source=cfg.track.source or None,
        should_stop=ctx.should_stop, start=start,
        progress=say), say, tries=2)
    return {"path": str(res.path), "duration": res.duration, "start": start,
            "start_why": why, "requested_seconds": seconds,
            "preflight": pre.to_dict(),
            "width": res.width, "height": res.height, "fps": res.fps}


def _save(ctx: Ctx, say) -> dict:
    """Write the project to disk.

    Its own stage because it is the slowest and least reliable thing the system
    does -- TouchDesigner routinely stops answering for one to three minutes
    mid-save -- and burying that inside another stage makes the other stage look
    hung. `save_project` quiesces first and treats a timeout as "wait and
    re-check" rather than a failure.
    """
    from . import sync
    return {"result": attempt(lambda: sync.save_project(ctx.client), say, tries=2,
                              delay=10.0)}


def _verify(ctx: Ctx, say) -> dict:
    from . import render as render_mod
    from .cues import CueTable
    ws, cfg = ctx.workspace, ctx.workspace.load_config()
    prev = ctx.run.stage("preview").detail.get("path") if ctx.run else None
    if not prev or not Path(prev).exists():
        return {"stage_skipped": True, "why": "no preview to measure"}
    dur = float(ctx.run.stage("preview").detail.get("duration") or 0) or 4.0
    times = [round(dur * f, 1) for f in (0.15, 0.5, 0.85)]
    say(f"sampling stills at {times}")
    made = render_mod.sample_frames(prev, times, ws.stills_dir)
    regions = cfg.video_type.regions(cfg) or {"frame": None}
    out, problems = [], []
    for img, t in zip(made, times):
        entry = {"time": t, "file": f"/api/stills/{img.name}"}
        for name, box in regions.items():
            stats = (render_mod.region_stats(img, *box) if box
                     else render_mod.region_stats(img))
            entry[name] = stats
        out.append(entry)
    # The invariant worth asserting automatically: no *letters* outside the band,
    # because that is the failure that shipped three times. Compare averages, not
    # peaks -- the glow blur is wider than the gap between the band edge and the
    # frame edge, so a thin bright rim below the band is bleed and is expected.
    # Measured on a good frame: below-band YMAX 69 but YAVG 0.0 and not a single
    # pixel over 100, against an in-band YAVG of 2.8.
    # ffmpeg's signalstats reports limited-range luma, where black is 16 and not
    # 0. Comparing raw YAVGs made every frame look guilty: 16.0 below the band
    # against 16.5 inside it is black against black.
    floor = 16.0
    if "lower" in regions and any(not (e.get("lower") or {}) for e in out):
        # A crop that could not be measured is not a crop that measured clean.
        problems.append(
            "the area below the band could not be measured, so nothing checked "
            "whether letters are escaping it")
    for e in out:
        lower, band = e.get("lower") or {}, e.get("band") or {}
        lo_avg = max(0.0, lower.get("YAVG", floor) - floor)
        band_avg = max(0.0, band.get("YAVG", floor) - floor)
        if band_avg > 0.1 and lo_avg > band_avg * 0.35:
            problems.append(
                f"{e['time']}s: letters below the band "
                f"(YAVG {lo_avg:.1f} against {band_avg:.1f} inside)")
    # Does the picture belong to this song, and is it all there? Nothing here
    # used to ask either question, which is how a render of a completely
    # different part of the track was written out as "verified with no
    # problems" -- every regional brightness check passed, because the frames
    # were perfectly good frames of the wrong thing.
    match = {}
    # Only for a renderer that draws them. `_push` already refuses to send
    # words to a beatsync type, but `cues.tsv` stays on disk -- so switching a
    # song from lyric_grid to pulse_grid made this correlate a wordless picture
    # against word times, report "the picture does not follow the words", burn a
    # second render on the repair, and then refuse a perfectly good take.
    cues = (CueTable.load(ws.cues_path).cues
            if cfg.video_type.needs_lyrics and ws.cues_path.exists() else [])
    prev_detail = ctx.run.stage("preview").detail if ctx.run else {}
    start = float(prev_detail.get("start") or 0.0)
    # The window in which a word is at full brightness, from this song's own
    # cueing rather than from a constant that only matched one configuration.
    cue = getattr(cfg.params, "cueing", None)
    plateau = ((cue.ramp_up, cue.ramp_up + cue.hold) if cue is not None
               else (0.12, 0.92))
    try:
        match = render_mod.measure_output(prev, [c.start for c in cues], start,
                                          plateau=plateau)
    except Exception as e:
        say(f"could not measure the finished file: {e}")
        problems.append(f"the finished file could not be measured: {e}")

    if match.get("checked"):
        ratio, follows = match.get("ratio"), match.get("follows_words")
        if ratio is not None:
            say(f"lit {match['bright_in_cue']:.0f} px during words against "
                f"{match['bright_outside']:.0f} px between them")
            if ratio < 1.5:
                problems.append(
                    f"the picture does not follow the words: "
                    f"{match['bright_in_cue']:.0f} lit pixels while a word is "
                    f"being sung against {match['bright_outside']:.0f} between "
                    f"words. The render is probably showing a different part of "
                    f"the song than the audio.")
        elif follows is not None:
            # Densely sung, so there are no frames between words to compare
            # against. How many words are lit still varies, and the picture
            # should track that.
            say(f"brightness tracks the words at {follows:+.2f}")
            if follows < 0.1:
                problems.append(
                    f"the picture does not follow the words: brightness tracks "
                    f"how many words are being sung at only {follows:+.2f}, "
                    f"where a render of this song scores well above zero. It is "
                    f"probably showing a different part of the song than the "
                    f"audio.")

        black = match.get("black_fraction", 0.0)
        if black > 0.02:
            problems.append(
                f"{100 * black:.0f}% of the frames are completely black "
                f"(longest run {match['longest_black_seconds']:.1f}s)")

        # Geometry drift shows here and nowhere else: a lost text calibration
        # dropped the row pitch from 53px to 40px, so the grid drew short and
        # the bottom third of every frame was empty, while every brightness
        # measurement of the part that *was* drawn stayed perfect.
        fill = match.get("frame_fill", 1.0)
        if fill < 0.75:
            problems.append(
                f"only {100 * fill:.0f}% of the frame height has anything drawn "
                f"in it; the grid is not filling the frame, which usually means "
                f"the text geometry is wrong")

        # A slow cook yields fewer frames than asked for, and the movie is built
        # from however many landed at a fixed rate -- so the picture is time
        # compressed against full-length audio and drifts further out all the
        # way through.
        wanted = float(prev_detail.get("requested_seconds") or 0.0)
        got = float(match.get("seconds") or 0.0)
        if wanted and got and abs(got - wanted) > max(1.0, wanted * 0.05):
            problems.append(
                f"the render is {got:.1f}s long but {wanted:.1f}s was asked for; "
                f"the picture is stretched or compressed against its audio")

    # Record the settings that produced this take, and whether it is trustworthy.
    #
    # "Trustworthy" now means the whole run was clean, not just this stage.
    # Earlier problems -- a build that could not calibrate the glyph geometry,
    # say -- used to land in a dict nobody read, and the file still got a marker
    # reading "verified with no problems".
    earlier = list(getattr(ctx.run, "problems", []) or [])
    ready = not problems and not earlier
    if earlier and not problems:
        say(f"not marking this take verified: {len(earlier)} earlier problem(s)")
    try:
        ws.write_take(Path(prev), ready=ready)
    except Exception as e:
        say(f"could not record the take: {e}")

    return {"stills": out, "regions": list(regions), "problems": problems,
            "earlier_problems": earlier, "ready": ready, "match": match}


def _forget_problems(problems: list[str], keys) -> None:
    """Drop the problems belonging to the stages that are about to run again.

    Problems are recorded as "<stage>: <note>", which is what makes this
    possible: a retry can forget its own findings without forgetting that the
    build could not calibrate the glyph geometry an hour earlier.
    """
    prefixes = tuple(f"{k}: " for k in keys)
    problems[:] = [p for p in problems if not p.startswith(prefixes)]


STAGES: list[tuple[str, str, Callable]] = [
    ("environment", "Prepare TouchDesigner", _environment),
    ("workspace", "Create the song folder", _workspace),
    ("ingest", "Separate, analyse, transcribe", _ingest),
    ("provision", "Build the network", _provision),
    ("describe", "Apply the description", _describe),
    ("push", "Push params and cues", _push),
    ("preview", "Render a preview", _preview),
    ("verify", "Measure the result", _verify),
    ("save", "Save the project", _save),
]


def new_run(song: str) -> Run:
    return Run(id=uuid.uuid4().hex[:8], song=song,
               stages=[Stage(key=k, title=t) for k, t, _ in STAGES])


def execute(run: Run, ctx: Ctx, on_change=None, from_stage: str | None = None) -> Run:
    """Walk the stages in order, stopping at the first failure.

    `from_stage` enters partway: everything before it is marked skipped rather
    than quietly not happening. That is what "update the preview" is — a look or
    cue change does not need the stems re-checked, and re-running ingest for it
    would be minutes of work to confirm nothing moved.
    """
    ctx.run = run                               # verify reads the preview's path
    run.state = RUNNING
    run.started = time.time()
    notify = on_change or (lambda: None)

    keys = [k for k, _t, _f in STAGES]
    start_at = keys.index(from_stage) if from_stage in keys else 0
    if start_at:
        # The workspace still has to be resolved, or later stages have nothing
        # to act on; it is cheap and idempotent.
        try:
            _workspace(ctx, lambda m: None)
        except Exception:
            pass
        for k in keys[:start_at]:
            sk = run.stage(k)
            sk.state = SKIPPED
            sk.message = "not needed for this update"
        notify()

    # A verify that fails is usually repairable state -- a lost calibration, a
    # stranded recorder, a timeline someone shrank. Preflight fixes exactly
    # those, and it runs at the top of the preview stage, so re-rendering once
    # is worth more than reporting a bad take. Once: a second failure is a real
    # one, and a loop would hide it.
    retried = False
    ordered = list(STAGES[start_at:])
    i = 0
    while i < len(ordered):
        key, _title, fn = ordered[i]
        i += 1
        if ctx.should_stop():
            run.state = STOPPED
            run.finished = time.time()
            notify()
            return run
        st = run.stage(key)
        st.state = RUNNING
        st.message = ""
        st.fraction = None
        st.started = t0 = time.time()
        notify()

        def say(m, frac=None, _st=st, _run=run):
            _st.message = str(m)
            if frac is not None:
                _st.fraction = max(0.0, min(1.0, float(frac)))
            _run.log.append(f"[{_st.key}] {m}")
            del _run.log[:-400]
            notify()

        try:
            detail = fn(ctx, say) or {}
            st.detail = detail if isinstance(detail, dict) else {"result": detail}
            # `stage_skipped` means this stage did nothing at all. It is NOT the
            # same as `skipped`, which ingest uses for the sub-steps it reused --
            # reading that list as a boolean marked a run "skipped" right after
            # it had separated a track and transcribed 380 words.
            st.state = SKIPPED if st.detail.get("stage_skipped") else DONE
            st.message = st.message or ("nothing to do" if st.state == SKIPPED else "done")
            # Every stage's problems, not just the verifier's. Build failures
            # used to be recorded in a dict nobody read: the calibration could
            # report "glyph placement may not line up with the frame" and the
            # run would still write "verified with no problems" beside the file.
            for note in st.detail.get("problems") or []:
                run.problems.append(f"{st.key}: {note}")
            for note in st.detail.get("warnings") or []:
                run.warnings.append(f"{st.key}: {note}")

            if (key == "verify" and st.detail.get("problems")
                    and not retried and not ctx.should_stop()):
                # Most ways a finished file measures badly are repairable state
                # -- a lost calibration, a stranded recorder, a timeline someone
                # shrank -- and preflight repairs exactly those at the top of
                # the preview stage. So render once more before giving up.
                # Once, deliberately: a second failure is a real one, and a loop
                # would hide it behind minutes of rendering.
                retried = True
                say("the finished file did not measure well; repairing and "
                    "rendering once more")
                redo = ("preview", "verify", "save")
                # Only the stages about to run again. This was `clear()`, which
                # also erased an ingest or provision problem -- and `_verify`
                # decides whether to write the "verified" marker from exactly
                # this list, so the retry could hand a marker to a take whose
                # run had failed earlier. That is the defect the comment above
                # `earlier = ...` was written to close, re-opened by the repair.
                _forget_problems(run.problems, redo)
                for again in redo:
                    back = run.stage(again)
                    back.state, back.message, back.detail = PENDING, "", {}
                ordered = [s for s in STAGES if s[0] in redo]
                i = 0
                notify()
                continue
        except Stopped:
            st.state = STOPPED
            st.message = "stopped"
            run.state = STOPPED
            run.finished = time.time()
            st.seconds = round(time.time() - t0, 1)
            notify()
            return run
        except Exception as e:
            st.state = FAILED
            st.message = f"{type(e).__name__}: {e}"
            st.detail = {"traceback": traceback.format_exc()[-3000:]}
            run.state = FAILED
            run.error = st.message
            run.finished = time.time()
            st.seconds = round(time.time() - t0, 1)
            notify()
            return run
        st.seconds = round(time.time() - t0, 1)
        notify()

    run.state = DONE
    run.finished = time.time()
    notify()
    return run


def start(run: Run, ctx: Ctx, on_change=None,
          from_stage: str | None = None) -> threading.Thread:
    th = threading.Thread(target=execute, args=(run, ctx, on_change, from_stage),
                          daemon=True)
    th.start()
    return th


def resume_point(run: Run) -> str | None:
    """The first stage that has not settled — where a resume picks up."""
    for st in run.stages:
        if st.state not in (DONE, SKIPPED):
            return st.key
    return None


def carry_over(old: Run, new: Run) -> None:
    """Bring a stopped run's finished stages into its replacement, so a resume
    shows what actually happened rather than relabelling real work as skipped."""
    for st in old.stages:
        if st.state in (DONE, SKIPPED):
            tgt = new.stage(st.key)
            if tgt is not None:
                tgt.state, tgt.message = st.state, st.message
                tgt.detail, tgt.seconds = st.detail, st.seconds
