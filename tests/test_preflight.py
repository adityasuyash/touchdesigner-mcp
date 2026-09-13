"""Preflight, against a stub TouchDesigner.

The checks matter more than the transport, and a stub makes every failure mode
reachable -- including the ones that are hard to arrange in a live project.
"""

from __future__ import annotations

import pytest

from lyricfield import preflight, sync
from lyricfield.config import Config
from lyricfield.cues import Cue, CueTable
from lyricfield.workspace import Workspace


class FakeTD:
    """Just enough TouchDesigner to answer what preflight asks."""

    def __init__(self, *, end=16072, range_end=16072, rate=60.0,
                 recorder=False, project=""):
        self.end, self.range_end, self.rate = end, range_end, rate
        self.recorder = recorder
        self.project = project          # the .toe TD is holding
        self.dats: dict[str, str] = {}

    # --- the surface preflight uses ---
    def run(self, code, timeout=None):
        if "project.folder" in code or "project.name" in code:
            return self.project
        if "rangelimit" in code:
            return repr({"rate": self.rate, "end": self.end,
                         "range_start": 1, "range_end": self.range_end,
                         "limit": "loop"})
        if "_mcp_movieout" in code:
            if "destroy" in code:
                self.recorder = False
                return "cleared"
            return "True" if self.recorder else "False"
        return ""

    def dat_text(self, path):
        if path not in self.dats:
            raise KeyError(path)
        return self.dats[path]

    def write(self, path, text):
        self.dats[path] = text

    def call(self, tool, **kw):
        if tool == "render":
            self.recorder = False
            return {}
        return {}


@pytest.fixture
def ws(tmp_path):
    w = Workspace.create("A Song", None, root=tmp_path)
    CueTable([Cue("one", 1.0, 1), Cue("two", 1.6, 1)]).save(w.cues_path)
    cfg = w.load_config()
    cfg.track.duration = 90.0
    w.save_config(cfg)
    return w


def healthy(ws, **kw):
    """A stub already holding everything the song should have pushed."""
    cfg = ws.load_config()
    kw.setdefault("project", str(ws.project))
    td = FakeTD(**kw)
    td.dats[sync.PARAMS_DAT] = sync.params_text(cfg)
    td.dats[sync.CALLBACKS] = cfg.video_type.field_source() or ""
    td.dats[sync.CUE_DAT] = CueTable.load(ws.cues_path).to_dat_text()
    return td, cfg


def test_a_healthy_project_needs_no_repair(ws, monkeypatch):
    td, cfg = healthy(ws)
    monkeypatch.setattr(sync, "pull_cues",
                        lambda c, dat=None: CueTable.from_dat_text(c.dats[sync.CUE_DAT]))
    res = preflight.run(td, cfg, ws, covers=60.0)
    assert res.ok, res.problems
    assert res.repaired == []


def test_a_short_play_range_is_widened(ws, monkeypatch):
    """The original bug: `end` long enough, the play range inherited from a
    90-second song, and every seek past it silently discarded."""
    td, cfg = healthy(ws, end=16072, range_end=5433)
    monkeypatch.setattr(sync, "pull_cues",
                        lambda c, dat=None: CueTable.from_dat_text(c.dats[sync.CUE_DAT]))
    called = {}

    def widen(client, seconds, **kw):
        called["seconds"] = seconds
        client.range_end = client.end        # what the real one does
        return {"seconds": seconds}

    monkeypatch.setattr(sync, "set_timeline_length", widen)
    res = preflight.run(td, cfg, ws, covers=200.0)
    assert "timeline and play range" in res.repaired
    assert called["seconds"] >= 200.0


def test_stale_parameters_are_repushed(ws, monkeypatch):
    td, cfg = healthy(ws)
    td.dats[sync.PARAMS_DAT] = "P = {}   # wiped"
    monkeypatch.setattr(sync, "pull_cues",
                        lambda c, dat=None: CueTable.from_dat_text(c.dats[sync.CUE_DAT]))
    monkeypatch.setattr(sync, "push_params",
                        lambda c, cfg: c.write(sync.PARAMS_DAT, sync.params_text(cfg)))
    res = preflight.run(td, cfg, ws, covers=60.0)
    assert "parameters" in res.repaired
    assert res.ok, res.problems


def test_a_push_that_does_not_take_is_reported_not_assumed(ws, monkeypatch):
    """The defect class this whole module exists for: the repair is attempted,
    has no effect, and nothing notices."""
    td, cfg = healthy(ws)
    td.dats[sync.PARAMS_DAT] = "P = {}   # wiped"
    monkeypatch.setattr(sync, "pull_cues",
                        lambda c, dat=None: CueTable.from_dat_text(c.dats[sync.CUE_DAT]))
    monkeypatch.setattr(sync, "push_params", lambda c, cfg: None)   # silently fails
    res = preflight.run(td, cfg, ws, covers=60.0)
    assert not res.ok
    assert any("fallback values" in p for p in res.problems)


def test_a_stale_cue_table_is_repushed(ws, monkeypatch):
    td, cfg = healthy(ws)
    td.dats[sync.CUE_DAT] = CueTable([Cue("only", 1.0, 1)]).to_dat_text()
    monkeypatch.setattr(sync, "pull_cues",
                        lambda c, dat=None: CueTable.from_dat_text(c.dats[sync.CUE_DAT]))
    monkeypatch.setattr(sync, "push_cues",
                        lambda c, t: c.write(sync.CUE_DAT, t.to_dat_text()))
    monkeypatch.setattr(sync, "reset_field_state", lambda c: None)
    res = preflight.run(td, cfg, ws, covers=60.0)
    assert "cue table" in res.repaired
    assert res.ok, res.problems


def test_a_stranded_recorder_is_cleared(ws, monkeypatch):
    """One aborted preview left the Movie File Out in the network and every
    later render refused to start."""
    td, cfg = healthy(ws, recorder=True)
    monkeypatch.setattr(sync, "pull_cues",
                        lambda c, dat=None: CueTable.from_dat_text(c.dats[sync.CUE_DAT]))
    res = preflight.run(td, cfg, ws, covers=60.0)
    assert "stranded recorder" in res.repaired
    assert res.ok, res.problems


def test_a_lyric_type_with_no_words_is_refused(ws, monkeypatch):
    """It would render an empty field for the length of the song and pass every
    brightness check there is."""
    CueTable([]).save(ws.cues_path)
    td, cfg = healthy(ws)
    monkeypatch.setattr(sync, "pull_cues", lambda c, dat=None: CueTable([]))
    res = preflight.run(td, cfg, ws, covers=60.0)
    assert not res.ok
    assert any("words" in p for p in res.problems)


def test_a_check_that_cannot_run_is_not_a_passing_check(ws, monkeypatch):
    td, cfg = healthy(ws)

    def explode(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(sync, "timeline_state", explode)
    res = preflight.run(td, cfg, ws, covers=60.0)
    assert not res.ok
    assert any("could not check" in p for p in res.problems)


def test_repair_can_be_turned_off_for_a_dry_run(ws, monkeypatch):
    td, cfg = healthy(ws, end=16072, range_end=5433)
    monkeypatch.setattr(sync, "pull_cues",
                        lambda c, dat=None: CueTable.from_dat_text(c.dats[sync.CUE_DAT]))
    res = preflight.run(td, cfg, ws, covers=200.0, repair=False)
    assert not res.ok
    assert res.repaired == []
