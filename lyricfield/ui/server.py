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
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import (analysis, pipeline, render as render_mod, separate as separate_mod,
                styles as styles_mod, sync, transcribe, workspace)
from ..config import Config
from ..cues import Cue, CueTable
from ..td_client import TDClient, TDError, TDUnavailable

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
STYLES_ROOT = ROOT / "styles"

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


class SeparateIn(BaseModel):
    track: str
    stem_root: str = str(separate_mod.DEFAULT_ROOT)
    model: str = separate_mod.DEFAULT_MODEL
    device: str | None = None
    force: bool = False


class KeyIn(BaseModel):
    api_key: str


class PrepareIn(BaseModel):
    """One call: separate, analyse, transcribe, persist."""
    track: str
    stem_root: str = str(separate_mod.DEFAULT_ROOT)
    model: str = separate_mod.DEFAULT_MODEL
    device: str | None = None
    groq_model: str = transcribe.DEFAULT_MODEL
    language: str | None = None
    prompt: str | None = None
    api_key: str | None = None
    force_separate: bool = False
    force_transcribe: bool = False


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

@app.get("/api/status")
def status():
    cfg = load_config()
    table = load_cues()
    return {
        "td_connected": client.ping(timeout=3.0),
        "td_url": client.url,
        "cues": len(table.cues),
        "lines": len(table.lines),
        "problems": table.problems(cfg.track.duration or None),
        "config_problems": cfg.validate(),
        "job": asdict(JOB),
    }


@app.get("/api/config")
def get_config():
    cfg = load_config()
    return {"config": {k: asdict(v) for k, v in vars(cfg).items()},
            "problems": cfg.validate()}


@app.post("/api/config")
def set_config(payload: dict):
    cfg = load_config()
    for section, values in payload.items():
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
            payload.track, root=payload.stem_root, model=payload.model,
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
            stem_root=payload.stem_root, model=payload.model,
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
            client, payload.output, payload.duration,
            vocals=payload.vocals, instrumental=payload.instrumental,
            fps=payload.fps, progress=say)
        return {"path": str(res.path), "duration": res.duration,
                "width": res.width, "height": res.height, "fps": res.fps}
    _run_job("render", job)
    return {"started": True}


@app.post("/api/stills")
def do_stills(payload: StillsIn):
    made = render_mod.sample_frames(payload.video, payload.times, stills_dir())
    cfg = load_config()
    g = cfg.grid
    band_y0 = int(g.band_top * g.height / g.vrows)
    band_y1 = int((g.band_top + g.band) * g.height / g.vrows)
    out = []
    for p, t in zip(made, payload.times):
        out.append({
            "time": t,
            "file": f"/stills/{p.name}",
            "band": render_mod.region_stats(p, 0, band_y0, g.width, band_y1 - band_y0),
            "lower": render_mod.region_stats(p, 0, band_y1, g.width,
                                             max(1, g.height - band_y1)),
        })
    return {"stills": out}


# --------------------------------------------------------------------------- songs

class SongIn(BaseModel):
    name: str
    source: str | None = None
    style: str | None = None


@app.get("/api/songs")
def list_songs():
    return {
        "songs": [w.to_dict() for w in workspace.list_workspaces()],
        "current": CURRENT.slug if CURRENT else None,
        "root": str(workspace.DEFAULT_ROOT),
    }


@app.post("/api/songs")
def create_song(payload: SongIn):
    ws = workspace.Workspace.create(payload.name, payload.source, style=payload.style)
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


class PreviewIn(BaseModel):
    at: float = 0.0
    seconds: float = 4.0


@app.get("/api/styles")
def list_styles():
    return {"styles": [s.to_dict(STYLES_ROOT)
                       for s in styles_mod.list_styles(STYLES_ROOT)]}


@app.post("/api/styles")
def save_style(payload: StyleIn):
    """Capture the current look as a reusable, named style."""
    cfg = load_config()
    st = styles_mod.Style.from_config(
        cfg, payload.name, payload.description,
        source_song=cfg.track.title or (CURRENT.slug if CURRENT else ""))
    st.save(STYLES_ROOT)
    return st.to_dict(STYLES_ROOT)


@app.post("/api/styles/{slug}/apply")
def apply_style(slug: str):
    try:
        st = styles_mod.get_style(slug, STYLES_ROOT)
    except FileNotFoundError as e:
        raise HTTPException(404, str(e)) from e
    cfg = st.apply_to(load_config())
    cfg.track.style = slug
    cfg.save(config_path())
    return {"applied": slug, "problems": cfg.validate()}


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
        return {"preview": f"/styles/{slug}/preview.mp4", "path": str(path)}
    _run_job("style-preview", job)
    return {"started": True}


@app.delete("/api/styles/{slug}")
def remove_style(slug: str):
    styles_mod.delete_style(slug, STYLES_ROOT)
    return {"deleted": slug}


@app.get("/api/job")
def job_status():
    return asdict(JOB)


# --------------------------------------------------------------------------- static

STILLS.mkdir(parents=True, exist_ok=True)
app.mount("/stills", StaticFiles(directory=STILLS), name="stills")

# style previews are served straight off disk so the dropdown can play them
STYLES_ROOT.mkdir(parents=True, exist_ok=True)
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
