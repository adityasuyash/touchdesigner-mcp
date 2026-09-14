"""Local control UI.

Everything the TouchDesigner build was driven by hand now has an endpoint:
transcribe a vocal stem, edit the cue table, analyse the instrumental, tune the
look, push to TD, render, and inspect stills from the finished file.

Runs locally and talks to TD over the same JSON-RPC the MCP client uses. Long
jobs (transcription, render) run on a background thread with pollable status,
because a render takes minutes and TD stalls while it works.
"""

from __future__ import annotations

import os
import threading
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import (analysis, pipeline, render as render_mod, run as run_mod,
                describe as describe_mod, separate as separate_mod,
                styles as styles_mod, sync,
                td_setup, transcribe, types as types_mod, workspace)
from ..config import Config
from ..cues import Cue, CueTable
from ..td_client import TDClient, TDError, TDUnavailable

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
STYLES_ROOT = ROOT / "styles"
BACKDROP_ROOT = STYLES_ROOT / "_backdrops"

app = FastAPI(title="lyricfield")
client = TDClient()

# The active song. When none is selected the server falls back to data/, which
# keeps the pre-workspace layout working.
CURRENT: workspace.Workspace | None = None


def _select(slug: str | None) -> None:
    global CURRENT
    CURRENT = workspace.Workspace.open(slug) if slug else None


def config_path() -> Path:
    return CURRENT.config_path if CURRENT else DATA / "config.toml"


def cues_path() -> Path:
    return CURRENT.cues_path if CURRENT else DATA / "cues.tsv"


def stills_dir() -> Path:
    return CURRENT.stills_dir if CURRENT else DATA / "stills"


# kept for the static mount; per-workspace stills are served through /api/stills
STILLS = DATA / "stills"


# --------------------------------------------------------------------------- jobs

@dataclass
class Job:
    name: str = ""
    state: str = "idle"          # idle | running | done | error
    message: str = ""
    result: dict = field(default_factory=dict)


JOB = Job()
_lock = threading.Lock()

# The automatic run. One at a time, because there is one TouchDesigner.
RUN: run_mod.Run | None = None
RUN_CTX: run_mod.Ctx | None = None      # holds the cancel signal for /stop
RUN_ARGS: dict = {}                     # what started it, so it can be redone
_run_lock = threading.Lock()


class RunIn(BaseModel):
    """Everything the system needs. After this, nothing is manual."""
    name: str
    source: str | None = None
    type: str | None = None
    style: str | None = None
    backdrop: str | None = None     # what fills the space around the words
    api_key: str | None = None
    language: str | None = None
    prompt: str | None = None
    preview_seconds: float | None = None
    start_seconds: float | None = None   # where to render from; None = auto-pick
    from_stage: str | None = None   # enter partway: "push" is an update
    force_separate: bool = False
    force_transcribe: bool = False
    length: str | None = None       # "full" renders the whole track
    describe: str | None = None     # words to turn into look settings


def _run_job(name: str, fn):
    def worker():
        try:
            out = fn(lambda m: _set(state="running", message=m))
            _set(state="done", message="finished", result=out or {})
        except Exception as e:
            _set(state="error", message=f"{type(e).__name__}: {e}",
                 result={"traceback": traceback.format_exc()[-2000:]})

    with _lock:
        if JOB.state == "running":
            raise HTTPException(409, f"{JOB.name} is already running")
        JOB.name, JOB.state, JOB.message, JOB.result = name, "running", "starting", {}
    threading.Thread(target=worker, daemon=True).start()


def _set(**kw):
    with _lock:
        for k, v in kw.items():
            setattr(JOB, k, v)


@app.post("/api/run")
def start_run(payload: RunIn):
    """Do the whole thing: prepare TouchDesigner, ingest, build, push, preview."""
    global RUN, RUN_CTX, RUN_ARGS
    with _run_lock:
        if RUN is not None and RUN.state == run_mod.RUNNING:
            raise HTTPException(409, f"run {RUN.id} is already going")
        if payload.api_key:
            transcribe.store_api_key(payload.api_key)
        RUN = run_mod.new_run(payload.name)
        RUN_ARGS = payload.model_dump()
        ctx = RUN_CTX = run_mod.Ctx(
            client=client, name=payload.name, source=payload.source or "",
            video_type=payload.type, style=payload.style,
            backdrop=payload.backdrop,
            options={k: v for k, v in {
                "language": payload.language, "prompt": payload.prompt,
                "preview_seconds": payload.preview_seconds,
                "start_seconds": payload.start_seconds,
                "length": payload.length,
                "describe": payload.describe,
                "force_separate": payload.force_separate,
                "force_transcribe": payload.force_transcribe}.items() if v})
        run_mod.start(RUN, ctx, on_change=_select_after_run,
                      from_stage=payload.from_stage)
    return RUN.to_dict()


def _select_after_run() -> None:
    """Keep the UI's selected song pointed at whatever the run is working on."""
    global CURRENT
    if RUN is None:
        return
    st = RUN.stage("workspace")
    if st and st.state == run_mod.DONE and st.detail.get("slug"):
        if CURRENT is None or CURRENT.slug != st.detail["slug"]:
            try:
                _select(st.detail["slug"])
            except FileNotFoundError:
                pass


@app.post("/api/run/stop")
def run_stop():
    """Ask the run to stop. It halts at the next point it can.

    A single blocking call into TouchDesigner cannot be interrupted -- TD stops
    answering for minutes while it saves -- so this is "stop as soon as
    possible", not "stop now", and the stage list keeps showing what it is doing
    until it gets there.
    """
    if RUN is None or RUN.state != run_mod.RUNNING or RUN_CTX is None:
        raise HTTPException(409, "nothing is running")
    RUN_CTX.stop.set()
    # Tear down any recording in flight. Without this the Movie File Out stays
    # in the network and the next render refuses to start -- so a single press
    # of Stop silently broke every generate after it.
    cleared = render_mod.stop_recording(client)
    return {"stopping": RUN.id, "recorder": cleared}


def _restart_from(from_stage: str | None, carry: run_mod.Run | None):
    global RUN, RUN_CTX
    args = dict(RUN_ARGS or {})
    args.pop("from_stage", None)
    RUN = run_mod.new_run(args.get("name") or (carry.song if carry else ""))
    if carry is not None:
        run_mod.carry_over(carry, RUN)
    RUN_CTX = run_mod.Ctx(
        client=client, name=args.get("name") or "", source=args.get("source") or "",
        video_type=args.get("type"), style=args.get("style"),
        options={k: v for k, v in {
            "language": args.get("language"), "prompt": args.get("prompt"),
            "preview_seconds": args.get("preview_seconds"),
            "length": args.get("length"), "describe": args.get("describe"),
            "start_seconds": args.get("start_seconds"),
            "force_separate": args.get("force_separate"),
            "force_transcribe": args.get("force_transcribe")}.items() if v})
    run_mod.start(RUN, RUN_CTX, on_change=_select_after_run, from_stage=from_stage)
    return RUN.to_dict()


@app.post("/api/run/resume")
def run_resume():
    """Carry on from the stage that was interrupted, keeping what finished."""
    if RUN is None or RUN.state == run_mod.RUNNING:
        raise HTTPException(409, "no stopped run to resume")
    if not (RUN_ARGS or {}).get("name"):
        raise HTTPException(409, "there is no previous run to resume")
    with _run_lock:
        return _restart_from(run_mod.resume_point(RUN), RUN)


@app.post("/api/run/restart")
def run_restart():
    """Start again from the top. Stages whose output already exists still skip
    their work -- that is the resumability, and what the redo options are for."""
    if RUN is not None and RUN.state == run_mod.RUNNING:
        raise HTTPException(409, "a run is already going")
    # Without this a restart with nothing to restart invents an "untitled" song
    # and fails at ingest for want of a source.
    if not (RUN_ARGS or {}).get("name"):
        raise HTTPException(409, "there is no previous run to restart")
    with _run_lock:
        return _restart_from(None, None)


@app.get("/api/run")
def run_status():
    return RUN.to_dict() if RUN else {"state": "idle", "stages": []}


@app.post("/api/songs/{slug}/provision")
def provision_song(slug: str):
    """Open or create this song's project in TouchDesigner, build it, push it."""
    _select(slug)
    assert CURRENT is not None

    def job(say):
        return CURRENT.provision(client, progress=say)
    _run_job("provision", job)
    return {"started": True}


@app.post("/api/render/full")
def render_full():
    """The full-length render — deliberate, not part of the automatic run."""
    if CURRENT is None:
        raise HTTPException(400, "select a song first")
    cfg = load_config()
    if not cfg.track.duration:
        raise HTTPException(400, "analyse the track first; its duration is unknown")

    ws, out = CURRENT, CURRENT.export_path()

    def job(say):
        res = render_mod.render(
            client, out, cfg.track.duration,
            vocals=cfg.track.vocals or None,
            instrumental=cfg.track.instrumental or None, progress=say)
        return {"path": str(res.path), "duration": res.duration}
    _run_job("render-full", job)
    return {"started": True, "output": str(out)}


# --------------------------------------------------------------------------- state

def load_config() -> Config:
    return Config.load(config_path())


def load_cues() -> CueTable:
    return CueTable.load(cues_path())


# --------------------------------------------------------------------------- models

class CueIn(BaseModel):
    word: str
    start: float
    line: int


class CuesIn(BaseModel):
    cues: list[CueIn]


class TranscribeIn(BaseModel):
    audio: str
    model: str = transcribe.DEFAULT_MODEL
    language: str | None = None
    prompt: str | None = None
    api_key: str | None = None


class AnalyseIn(BaseModel):
    instrumental: str


def _stem_root(explicit: str | None) -> str:
    """Where stems go: the song's own `stems/` unless overridden.

    The shared `~/separated` tree is keyed on the source filename, so two songs
    whose audio files are named alike overwrite each other's stems -- and a
    song folder that is supposed to travel as one unit does not contain them.
    """
    if explicit:
        return explicit
    return str(CURRENT.stems_dir) if CURRENT else str(separate_mod.DEFAULT_ROOT)


class SeparateIn(BaseModel):
    track: str
    stem_root: str | None = None
    # The model is not a user choice: htdemucs is Demucs' own recommended
    # default and the only one the UI offers. Kept overridable for the CLI.
    model: str = separate_mod.DEFAULT_MODEL
    device: str | None = None
    force: bool = False


class KeyIn(BaseModel):
    api_key: str


class PrepareIn(BaseModel):
    """One call: separate, analyse, transcribe, persist."""
    track: str
    stem_root: str | None = None
    model: str = separate_mod.DEFAULT_MODEL
    device: str | None = None
    groq_model: str = transcribe.DEFAULT_MODEL
    language: str | None = None
    prompt: str | None = None
    api_key: str | None = None
    force_separate: bool = False
    force_transcribe: bool = False


def _out_path(raw: str) -> Path:
    """Expand and absolutise a user-typed output path.

    `~` never expands on its own, and TouchDesigner resolves anything relative
    against the project folder -- so an unexpanded path created a literal "~"
    directory inside the song folder while this side waited for a file that
    would never appear.
    """
    p = Path(raw).expanduser()
    if not p.is_absolute():
        base = CURRENT.exports_dir if CURRENT else DATA
        p = base / p
    return p


class RenderIn(BaseModel):
    output: str
    duration: float
    vocals: str | None = None
    instrumental: str | None = None
    fps: int = 30


class StillsIn(BaseModel):
    video: str
    times: list[float]


# --------------------------------------------------------------------------- api

_ping_cache = {"at": 0.0, "up": False}


def _td_connected(max_age: float = 5.0) -> bool:
    """Cached liveness. The UI polls status every 2s and the ping timeout is 3s,
    so an unresponsive TouchDesigner made requests overlap and pile up exactly
    when the UI most needs to stay answering."""
    now = time.monotonic()
    if now - _ping_cache["at"] > max_age:
        _ping_cache["up"] = client.ping(timeout=2.0)
        _ping_cache["at"] = now
    return _ping_cache["up"]


@app.get("/api/status")
def status():
    cfg = load_config()
    table = load_cues()
    return {
        # The browser ticks a live timer against stage start times, which are
        # this process's clock. Send ours so it can measure the difference
        # rather than assume the two agree.
        "now": time.time(),
        "td_connected": _td_connected(),
        "type": cfg.type,
        "td_url": client.url,
        "cues": len(table.cues),
        "lines": len(table.lines),
        "problems": table.problems(cfg.track.duration or None),
        "config_problems": cfg.validate(),
        "job": asdict(JOB),
        "run": RUN.to_dict() if RUN else None,
    }


@app.get("/api/config")
def get_config():
    cfg = load_config()
    return {"type": cfg.type,
            "config": cfg.sections(),
            "sections": list(cfg.video_type.section_names()),
            "ranges": cfg.video_type.ranges(),
            "controls": cfg.video_type.controls(cfg.params),
            "problems": cfg.validate()}


@app.post("/api/control")
def set_control(payload: dict):
    """Move one named control, which moves the group of tunables behind it."""
    cfg = load_config()
    key, value = payload.get("key", ""), float(payload.get("value", 0))
    try:
        changed = cfg.video_type.apply_control(cfg.params, key, value)
    except KeyError as e:
        raise HTTPException(400, str(e))
    cfg.save(config_path())
    return {"saved": True, "changed": changed,
            "config": cfg.sections(),
            "controls": cfg.video_type.controls(cfg.params),
            "problems": cfg.validate()}


@app.post("/api/config")
def set_config(payload: dict):
    cfg = load_config()
    for section, values in payload.items():
        if section in ("type", "track"):
            # `track` holds measured facts written by the analyse stage. The UI
            # posts the whole config back, so accepting it here silently reverted
            # a fresh analysis to whatever the browser last loaded.
            continue
        target = getattr(cfg, section, None)
        if target is None:
            continue
        for k, v in values.items():
            if hasattr(target, k):
                setattr(target, k, v)
    problems = cfg.validate()
    cfg.save(config_path())
    return {"saved": True, "problems": problems}


@app.get("/api/cues")
def get_cues():
    table = load_cues()
    cfg = load_config()
    return {
        "cues": [asdict(c) for c in table.cues],
        "lines": {str(k): table.line_text(k) for k in sorted(table.lines)},
        "problems": table.problems(cfg.track.duration or None),
    }


@app.post("/api/cues")
def set_cues(payload: CuesIn):
    table = CueTable([Cue(c.word, c.start, c.line) for c in payload.cues])
    table.save(cues_path())
    return {"saved": len(table.cues), "problems": table.problems()}


def _remember_key(key: str | None) -> str | None:
    """A key typed into the UI is stored, not just used once.

    Without this the field is a re-entry prompt rather than storage: the user
    retypes the same secret on every page load. Supplying it once here is
    enough forever after; transcribe.api_key() finds it on disk.
    """
    if key and key.strip():
        transcribe.store_api_key(key)
    return key


@app.get("/api/key")
def key_status():
    """Does a key already exist, and where did it come from?"""
    if os.environ.get("GROQ_API_KEY", "").strip():
        return {"stored": True, "source": "environment"}
    if transcribe.stored_api_key():
        return {"stored": True, "source": str(transcribe.KEY_FILE)}
    return {"stored": False, "source": ""}


@app.post("/api/key")
def key_store(payload: KeyIn):
    path = transcribe.store_api_key(payload.api_key)
    return {"stored": True, "source": str(path)}


@app.post("/api/transcribe")
def do_transcribe(payload: TranscribeIn):
    def job(say):
        say("uploading to Groq")
        table = transcribe.transcribe_to_cues(
            payload.audio, key=_remember_key(payload.api_key), model=payload.model,
            language=payload.language, prompt=payload.prompt)
        table.save(cues_path())
        say(f"{len(table.cues)} words")
        return {"cues": len(table.cues), "lines": len(table.lines),
                "problems": table.problems()}
    _run_job("transcribe", job)
    return {"started": True}


@app.post("/api/separate")
def do_separate(payload: SeparateIn):
    def job(say):
        stems = separate_mod.separate(
            payload.track, root=_stem_root(payload.stem_root), model=payload.model,
            device=payload.device, force=payload.force, progress=say)
        cfg = load_config()
        cfg.track.vocals = str(stems.vocals)
        cfg.track.instrumental = str(stems.instrumental)
        cfg.save(config_path())
        return stems.to_dict()
    _run_job("separate", job)
    return {"started": True}


@app.post("/api/prepare")
def do_prepare(payload: PrepareIn):
    """Separate, analyse and transcribe in one pass. Stages whose output already
    exists are skipped, so this is safe to re-run."""
    def job(say):
        res = pipeline.prepare(
            payload.track, config_path(), cues_path(),
            stem_root=_stem_root(payload.stem_root), model=payload.model,
            device=payload.device, groq_key=_remember_key(payload.api_key),
            groq_model=payload.groq_model, language=payload.language,
            prompt=payload.prompt, force_separate=payload.force_separate,
            force_transcribe=payload.force_transcribe, progress=say)
        return res.to_dict()
    _run_job("prepare", job)
    return {"started": True}


@app.post("/api/analyse")
def do_analyse(payload: AnalyseIn):
    def job(say):
        say("decoding and analysing")
        res = analysis.analyse(payload.instrumental)
        cfg = load_config()
        cfg.track.instrumental = payload.instrumental
        cfg.track.duration = res.duration
        cfg.track.kick_in = res.kick_in
        cfg.track.high_in = res.high_in
        cfg.track.beat_period = res.beat_period
        cfg.track.beat_anchor = res.beat_anchor
        cfg.track.hold_windows = [list(w) for w in res.hold_windows]
        cfg.save(config_path())
        return res.to_dict()
    _run_job("analyse", job)
    return {"started": True}


@app.post("/api/td/push")
def td_push():
    cfg = load_config()
    problems = cfg.validate()
    if problems:
        raise HTTPException(400, {"problems": problems})
    # The guard exists and works; this path simply never consulted it, so a push
    # could write one song's cues and params into another song's project.
    if CURRENT is not None and not CURRENT.is_open_in(client):
        raise HTTPException(409, {
            "error": f"TouchDesigner is not running {CURRENT.slug}; refusing to "
                     "push this song's data into another song's project",
            "fix": "provision this song first",
        })
    try:
        done = sync.push_all(client, cfg, load_cues())
    except (TDError, TDUnavailable) as e:
        raise HTTPException(503, str(e)) from e
    return {"pushed": done}


@app.post("/api/td/pull-cues")
def td_pull_cues():
    """Recover a cue table that only exists inside the .toe."""
    try:
        table = sync.pull_cues(client)
    except (TDError, TDUnavailable) as e:
        raise HTTPException(503, str(e)) from e
    if not table.cues:
        raise HTTPException(404, "no cue rows found in the project")
    table.save(cues_path())
    return {"recovered": len(table.cues), "lines": len(table.lines)}


@app.post("/api/td/save")
def td_save():
    def job(say):
        say("quiescing and saving (TD may stall for minutes)")
        return {"result": sync.save_project(client)}
    _run_job("save", job)
    return {"started": True}


@app.post("/api/render")
def do_render(payload: RenderIn):
    def job(say):
        res = render_mod.render(
            client, _out_path(payload.output), payload.duration,
            vocals=payload.vocals, instrumental=payload.instrumental,
            fps=payload.fps, progress=say)
        return {"path": str(res.path), "duration": res.duration,
                "width": res.width, "height": res.height, "fps": res.fps}
    _run_job("render", job)
    return {"started": True}


@app.get("/api/stills/{name}")
def get_still(name: str):
    """Stills live in the active song's exports/stills, not the shared data dir,
    so they are served by name through here rather than a fixed static mount."""
    p = (stills_dir() / name).resolve()
    if p.parent != stills_dir().resolve() or not p.exists():
        raise HTTPException(404, "no such still")
    return FileResponse(p)


@app.post("/api/stills")
def do_stills(payload: StillsIn):
    made = render_mod.sample_frames(_out_path(payload.video), payload.times,
                                    stills_dir())
    cfg = load_config()
    regions = cfg.video_type.regions(cfg) or {"frame": None}
    out = []
    for p, t in zip(made, payload.times):
        entry = {"time": t, "file": f"/api/stills/{p.name}"}
        for name, box in regions.items():
            entry[name] = (render_mod.region_stats(p, *box) if box
                           else render_mod.region_stats(p))
        out.append(entry)
    return {"stills": out, "regions": list(regions)}


# --------------------------------------------------------------------------- types

@app.get("/api/types")
def list_video_types():
    """The renderers a song can be made as. Ingest is shared; these differ."""
    return {"types": [t.to_dict() for t in types_mod.list_types()],
            "default": types_mod.DEFAULT_TYPE}


@app.get("/api/backdrops")
def list_backdrops():
    """What can sit behind the words, for the types that have words.

    Presets over the `backdrop` tunables rather than an enum, so every one of
    them is still reachable from a slider and from a written description.
    """
    out = []
    for vt in types_mod.list_types():
        mod = getattr(vt, "_params_module", lambda: None)()
        for key, label, why, deltas in getattr(mod, "BACKDROPS", ()):
            out.append({"type": vt.slug, "key": key, "name": label,
                        "description": why, "sets": deltas,
                        "preview": f"/styles/_backdrops/{vt.slug}/{key}/preview.mp4",
                        "has_preview": (BACKDROP_ROOT / vt.slug / key
                                        / "preview.mp4").exists()})
    return {"backdrops": out}


@app.post("/api/songs/{slug}/type")
def set_song_type(slug: str, payload: dict):
    _select(slug)
    assert CURRENT is not None
    try:
        cfg = CURRENT.set_type(payload.get("type", ""))
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {"type": cfg.type, "problems": cfg.validate()}


# -------------------------------------------------------------------- browsing

AUDIO_EXT = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".aiff", ".aif",
             ".opus", ".wma"}


@app.get("/api/browse")
def browse(path: str | None = None):
    """List folders and audio files, so the UI can offer a file picker.

    A browser deliberately withholds the real path from `<input type="file">`,
    and the pipeline needs a path it can hand to ffmpeg and Demucs. Since the
    server is on the same machine and bound to localhost, it can do the listing.
    """
    here = Path(path).expanduser() if path else Path.home()
    try:
        here = here.resolve()
        if not here.is_dir():
            here = here.parent
        entries = sorted(here.iterdir(), key=lambda p: p.name.lower())
    except (OSError, RuntimeError) as e:
        raise HTTPException(400, f"cannot read {here}: {e}") from e

    dirs, files = [], []
    for e in entries:
        if e.name.startswith("."):
            continue
        try:
            if e.is_dir():
                dirs.append({"name": e.name, "path": str(e)})
            elif e.suffix.lower() in AUDIO_EXT:
                files.append({"name": e.name, "path": str(e),
                              "mb": round(e.stat().st_size / 1048576, 1)})
        except OSError:
            continue

    home = Path.home()
    shortcuts = [{"name": n, "path": str(home / n)}
                 for n in ("Music", "Desktop", "Downloads", "Documents")
                 if (home / n).is_dir()]
    shortcuts.insert(0, {"name": "Home", "path": str(home)})
    return {
        "path": str(here),
        "parent": str(here.parent) if here.parent != here else None,
        "crumbs": [{"name": p.name or "/", "path": str(p)}
                   for p in reversed([here, *here.parents])][-5:],
        "dirs": dirs, "files": files, "shortcuts": shortcuts,
    }


# --------------------------------------------------------------------------- songs

class SongIn(BaseModel):
    name: str
    source: str | None = None
    type: str | None = None
    style: str | None = None
    backdrop: str | None = None     # what fills the space around the words


@app.get("/api/songs")
def list_songs():
    return {
        "songs": [w.to_dict() for w in workspace.list_workspaces()],
        "current": CURRENT.slug if CURRENT else None,
        "root": str(workspace.DEFAULT_ROOT),
    }


@app.post("/api/songs")
def create_song(payload: SongIn):
    ws = workspace.Workspace.create(payload.name, payload.source,
                                    video_type=payload.type, style=payload.style)
    cfg = ws.load_config()
    cfg.track.title = payload.name
    ws.save_config(cfg)
    _select(ws.slug)
    return ws.to_dict()


@app.post("/api/songs/{slug}/select")
def select_song(slug: str):
    try:
        _select(slug)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return {"current": slug, "project_open_in_td": CURRENT.is_open_in(client)}


@app.post("/api/songs/{slug}/fork-project")
def fork_project(slug: str):
    """Save whatever TD has open into this song's folder as project.toe."""
    _select(slug)
    assert CURRENT is not None

    def job(say):
        say("saving TD project into the song folder")
        path = CURRENT.fork_project_from_current(client)
        return {"project": str(path)}
    _run_job("fork-project", job)
    return {"started": True}


# -------------------------------------------------------------------------- styles

class StyleIn(BaseModel):
    name: str
    description: str = ""


class DescribeIn(BaseModel):
    text: str
    name: str = ""            # given only when the result is being kept


# The look in force before a description was tried, so rejecting one costs
# nothing. Module-level because it belongs to the browser session, not to a run.
_CUSTOM_BEFORE: dict = {}


class PreviewIn(BaseModel):
    at: float = 0.0
    seconds: float = 4.0


@app.get("/api/styles")
def list_styles(type: str | None = None):
    """Styles for one video type, or all of them. A style only means anything
    for the renderer it was made for."""
    out = []
    for st in styles_mod.list_styles(STYLES_ROOT, type=type):
        d = st.to_dict(STYLES_ROOT)
        try:
            d["family"] = types_mod.get_type(st.type).family
        except KeyError:
            d["family"] = "lyric"
        out.append(d)
    return {"styles": out}


@app.post("/api/styles/custom")
def custom_style(payload: DescribeIn):
    """Describe a style in words; get a preview of it back, and keep it or not.

    The three pieces already existed separately -- describing settings, saving a
    style, capturing a preview from the placeholder words. This joins them into
    the one flow that makes a style *creatable* rather than only savable: say
    what you want, watch it, then decide.

    Trying costs nothing. The current settings are stashed before anything is
    applied and put straight back by /api/styles/custom/cancel, so a description
    that comes back wrong leaves no trace.
    """
    global _CUSTOM_BEFORE
    cfg = load_config()
    _CUSTOM_BEFORE = cfg.sections()
    try:
        prop = describe_mod.propose(cfg, payload.text)
    except describe_mod.DescribeError as e:
        raise HTTPException(400, str(e))
    if prop.problems:
        raise HTTPException(422, "; ".join(prop.problems))
    cfg.save(config_path())
    try:
        sync.push_params(client, cfg)
    except Exception:
        pass

    # The preview is rendered from the placeholder words, never the loaded song,
    # so the style stays something you can carry to the next track.
    draft = styles_mod.Style.from_config(
        cfg, payload.name or "Draft", prop.why,
        source_song=cfg.track.title or (CURRENT.slug if CURRENT else ""))

    def job(say):
        path = styles_mod.capture_preview(
            client, draft, at=1.0, seconds=4.0, root=STYLES_ROOT, progress=say)
        return {"preview": draft.preview_url(), "path": str(path),
                "slug": draft.slug}
    _run_job("custom-style", job)
    out = prop.to_dict()
    out["requested"] = out.pop("controls")
    return {**out, "slug": draft.slug, "previewing": True,
            "controls": cfg.video_type.controls(cfg.params)}


@app.post("/api/styles/custom/keep")
def custom_style_keep(payload: StyleIn):
    """Name the described look and keep it, preview and all.

    The preview was already rendered against the draft, so it moves across
    rather than being made again -- re-rendering would cost another minute and
    could come out subtly different from the thing that was approved.
    """
    import shutil
    cfg = load_config()
    st = styles_mod.Style.from_config(
        cfg, payload.name, payload.description,
        source_song=cfg.track.title or (CURRENT.slug if CURRENT else ""))
    st.save(STYLES_ROOT)
    # Record which style the song is now wearing. Without this the config keeps
    # naming whatever was applied before while holding the new values, so the
    # two disagree and nothing notices.
    cfg.track.style = st.slug
    cfg.save(config_path())
    draft = STYLES_ROOT / cfg.type / "draft"
    dest = st.dir(STYLES_ROOT)
    for name in ("preview.mp4", "preview.png"):
        src = draft / name
        if src.exists():
            shutil.move(str(src), str(dest / name))
    if draft.exists() and not any(draft.iterdir()):
        draft.rmdir()
    global _CUSTOM_BEFORE
    _CUSTOM_BEFORE = {}
    return st.to_dict(STYLES_ROOT)


@app.post("/api/styles/custom/cancel")
def custom_style_cancel():
    """Put back whatever was in place before the description was tried."""
    global _CUSTOM_BEFORE
    if not _CUSTOM_BEFORE:
        raise HTTPException(409, "nothing to undo")
    cfg = load_config()
    for section, values in _CUSTOM_BEFORE.items():
        target = getattr(cfg, section, None)
        if target is None or not isinstance(values, dict):
            continue
        for k, v in values.items():
            if hasattr(target, k):
                setattr(target, k, v)
    cfg.save(config_path())
    _CUSTOM_BEFORE = {}
    # The draft's preview was only ever evidence for a decision that has now
    # been made the other way.
    import shutil
    draft = STYLES_ROOT / cfg.type / "draft"
    if draft.exists():
        shutil.rmtree(draft, ignore_errors=True)
    try:
        sync.push_params(client, cfg)
    except Exception:
        pass
    return {"restored": True, "controls": cfg.video_type.controls(cfg.params)}


@app.post("/api/styles")
def save_style(payload: StyleIn):
    """Capture the current look as a reusable, named style."""
    cfg = load_config()
    st = styles_mod.Style.from_config(
        cfg, payload.name, payload.description,
        source_song=cfg.track.title or (CURRENT.slug if CURRENT else ""))
    st.save(STYLES_ROOT)
    return st.to_dict(STYLES_ROOT)


@app.post("/api/describe")
def describe_look(payload: DescribeIn):
    """Turn a description into settings and apply them to the live config.

    Nothing is named or stored as a style here: the settings land on the current
    song so the next preview shows them, and the result is reported so the UI can
    say what moved. Keeping it is a separate, deliberate step -- POST /api/styles
    once a preview has been seen and approved.
    """
    cfg = load_config()
    try:
        prop = describe_mod.propose(cfg, payload.text)
    except describe_mod.DescribeError as e:
        raise HTTPException(400, str(e))
    if prop.problems:
        raise HTTPException(
            422, "the proposed settings are not valid: " + "; ".join(prop.problems))
    cfg.save(config_path())
    pushed = False
    try:
        sync.push_params(client, cfg)
        pushed = True
    except Exception:
        pass          # the settings are saved either way; TD may simply be shut
    # `requested` is what was asked for, `controls` is where things actually
    # landed after clamping and reconciliation -- they differ whenever a control
    # was pushed past what the others allow, and the UI shows the latter.
    payload_out = prop.to_dict()
    payload_out["requested"] = payload_out.pop("controls")
    return {**payload_out, "pushed": pushed,
            "controls": cfg.video_type.controls(cfg.params),
            "config": cfg.sections()}


@app.get("/api/describe/available")
def describe_available():
    return {"available": describe_mod.available()}


@app.post("/api/styles/{slug}/apply")
def apply_style(slug: str):
    try:
        st = styles_mod.get_style(slug, STYLES_ROOT)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    cfg = load_config()
    if cfg.type != st.type:
        cfg = cfg.with_type(st.type)     # the style decides the renderer
    cfg = st.apply_to(cfg)
    cfg.track.style = slug
    cfg.save(config_path())
    return {"applied": slug, "type": cfg.type, "problems": cfg.validate()}


@app.post("/api/styles/{slug}/preview")
def make_preview(slug: str, payload: PreviewIn):
    """Record a short loop of the current TD state as this style's preview."""
    try:
        st = styles_mod.get_style(slug, STYLES_ROOT)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e

    def job(say):
        path = styles_mod.capture_preview(
            client, st, at=payload.at, seconds=payload.seconds,
            root=STYLES_ROOT, progress=say)
        return {"preview": st.preview_url(), "path": str(path)}
    _run_job("style-preview", job)
    return {"started": True}


@app.delete("/api/styles/{slug}")
def remove_style(slug: str):
    styles_mod.delete_style(slug, STYLES_ROOT)
    return {"deleted": slug}


@app.get("/api/takes")
def list_takes():
    if CURRENT is None:
        return {"takes": []}
    return {"takes": CURRENT.takes()}


@app.get("/api/takes/file/{name}")
def take_file(name: str, download: bool = False):
    """Serve a rendered take so the browser can play it, or save it.

    Exports live in the song's own folder, not a static mount, so they are
    served by name from here -- the same shape as /api/stills/{name}.

    `download=1` attaches a filename, which is what turns the same response from
    something the <video> element streams into something the browser saves. It
    has to be opt-in for exactly that reason: setting it unconditionally would
    break playback, since this one route does both jobs.
    """
    if CURRENT is None:
        raise HTTPException(404, "no song selected")
    p = (CURRENT.exports_dir / name).resolve()
    if p.parent != CURRENT.exports_dir.resolve() or not p.exists():
        raise HTTPException(404, "no such take")
    return FileResponse(p, filename=p.name if download else None)


@app.post("/api/takes/{name}/restore")
def restore_take(name: str):
    if CURRENT is None:
        raise HTTPException(400, "select a song first")
    try:
        cfg = CURRENT.restore_take(name)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    return {"restored": name, "type": cfg.type, "problems": cfg.validate()}


@app.get("/api/job")
def job_status():
    return asdict(JOB)


# --------------------------------------------------------------------------- static

STILLS.mkdir(parents=True, exist_ok=True)
app.mount("/stills", StaticFiles(directory=STILLS), name="stills")

# style previews are served straight off disk so the dropdown can play them
STYLES_ROOT.mkdir(parents=True, exist_ok=True)
# Backdrop previews live under the styles mount but are not styles: `_style_dirs`
# only yields a folder holding a `style.toml`, so this one is invisible to
# `list_styles` while still being served and still being tracked by the
# `!styles/**/preview.mp4` negation in .gitignore.
BACKDROP_ROOT.mkdir(parents=True, exist_ok=True)
app.mount("/styles", StaticFiles(directory=STYLES_ROOT), name="styles")

_static = Path(__file__).parent / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=_static), name="static")


@app.get("/")
def index():
    return FileResponse(_static / "index.html")


def main() -> int:
    import argparse
    import uvicorn
    ap = argparse.ArgumentParser(description="lyricfield control UI")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    if not config_path().exists():
        Config().save(config_path())
    uvicorn.run(app, host=a.host, port=a.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
