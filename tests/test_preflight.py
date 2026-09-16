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
                 recorder=False, project="", script_errors="", params_read=None):
        self.end, self.range_end, self.rate = end, range_end, rate
        self.recorder = recorder
        self.project = project          # the .toe TD is holding
        self.dats: dict[str, str] = {}
        # Whether the field script could make anything of the params DAT, as
        # its own stats report it. None is "it has not cooked yet", which is
        # what a stub with nothing to say should answer.
        self.params_read = params_read
        # What TouchDesigner says is wrong with the Script TOP. A fake that
        # cannot answer this is an incomplete fake: a script whose text matches
        # the repo byte for byte can still raise on every cook, which is how a
        # broken render once took thirty minutes to report the wrong thing.
        self.script_errors = script_errors

    # --- the surface preflight uses ---
    def run(self, code, timeout=None):
        if "project.folder" in code or "project.name" in code:
            return self.project
        if "rangelimit" in code:
            return repr({"rate": self.rate, "end": self.end,
                         "range_start": 1, "range_end": self.range_end,
                         "limit": "loop"})
        if "params_missing" in code:
            return "" if self.params_read is None else str(int(self.params_read))
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

    def op_errors(self, path):
        return self.script_errors

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


# -------------------------------------------------- a script that cannot run

def test_a_field_script_that_raises_is_a_problem(cfg, ws):
    """Matching text is not a working script.

    The check used to stop at comparing the pushed text with the repo's, and a
    body that raised `NameError` on every cook matched its own source exactly.
    It passed, the render started, nothing was ever drawn, and the failure
    arrived a timeout later as "no valid container" -- the symptom, not the
    cause.
    """
    td = FakeTD(project=str(ws.project))
    td.dats[sync.CALLBACKS] = cfg.video_type.field_source()
    td.dats[sync.PARAMS_DAT] = sync.params_text(cfg)
    td.script_errors = ("Error: Traceback (most recent call last):\n"
                        "NameError: name '_read_drums' is not defined")
    res = preflight.run(td, cfg, ws, covers=10.0, progress=lambda m: None)
    assert not res.ok
    assert any("does not run" in p and "_read_drums" in p for p in res.problems), \
        res.problems


def test_a_healthy_field_script_is_not_a_problem(cfg, ws):
    td = FakeTD(project=str(ws.project))
    td.dats[sync.CALLBACKS] = cfg.video_type.field_source()
    td.dats[sync.PARAMS_DAT] = sync.params_text(cfg)
    res = preflight.run(td, cfg, ws, covers=10.0, progress=lambda m: None)
    assert not [p for p in res.problems if "does not run" in p], res.problems


def test_a_renderer_that_cannot_read_its_params_is_reported(ws, monkeypatch):
    """The DAT matching what was pushed is not the same question as the script
    being able to read it, and stopping at the first is how eight renderers ran
    every render on the defaults compiled into them. `sync` writes a Python
    module; those eight parsed the text as JSON; nothing failed.
    """
    td, cfg = healthy(ws, params_read=False)
    monkeypatch.setattr(sync, "pull_cues",
                        lambda c, dat=None: CueTable.from_dat_text(c.dats[sync.CUE_DAT]))
    res = preflight.run(td, cfg, ws, covers=60.0)
    assert any("cannot read the parameters" in p for p in res.problems), res.problems


def test_a_renderer_that_can_read_its_params_is_not_reported(ws, monkeypatch):
    td, cfg = healthy(ws, params_read=True)
    monkeypatch.setattr(sync, "pull_cues",
                        lambda c, dat=None: CueTable.from_dat_text(c.dats[sync.CUE_DAT]))
    res = preflight.run(td, cfg, ws, covers=60.0)
    assert res.ok, res.problems


def test_missing_footage_is_refused_rather_than_rendered(tmp_path):
    """The one path a person types rather than one ingest produces, so it can
    be wrong from the moment a song is made."""
    from lyricfield import preflight

    cfg = Config()
    cfg.track.plate = str(tmp_path / "gone.mp4")
    res = preflight.Result()
    preflight._plate_readable(FakeTD(), cfg, None, 0.0, False, res, lambda m: None)
    assert any("footage for this song is gone" in m for m in res.problems)


def test_footage_touchdesigner_cannot_decode_is_refused(tmp_path):
    """A Movie File In pointed at something it cannot read cooks BLACK and
    reports nothing. The lettering still draws and every brightness check
    passes, which is the whole class this module exists to refuse."""
    from lyricfield import preflight

    clip = tmp_path / "broken.mp4"
    clip.write_bytes(b"not a movie")
    cfg = Config()
    cfg.track.plate = str(clip)

    class Undecodable(FakeTD):
        def run(self, code, *a, **k):
            return "0 0" if "plate" in code else super().run(code, *a, **k)

    res = preflight.Result()
    preflight._plate_readable(Undecodable(), cfg, None, 0.0, False, res,
                              lambda m: None)
    assert any("cannot decode" in m for m in res.problems)


def test_a_song_with_no_footage_is_not_asked_about_it(tmp_path):
    from lyricfield import preflight

    cfg = Config()
    res = preflight.Result()
    preflight._plate_readable(FakeTD(), cfg, None, 0.0, False, res, lambda m: None)
    assert res.problems == []


def test_a_picked_beat_whose_driver_never_cooked_is_refused():
    """The question the preview path asks and the render path never did.

    `fx_drive` sets its siblings' parameters as a side effect of cooking, so a
    driver nothing cooks leaves the whole chain passing the word layer through
    untouched -- while the network is built, the params are right and the drum
    table is full, so every other check here passes. Measured on a real
    project: a render with `punch` picked came out identical to one with no
    beat at all.
    """
    from lyricfield import preflight, sync

    cfg = Config()
    cfg.with_beat("punch")
    assert cfg.response.active(), "punch switches something on"

    saved = sync.drums_were_read
    sync.drums_were_read = lambda client, container=None: None   # never cooked
    try:
        res = preflight.Result()
        preflight._beat_is_driven(FakeTD(), cfg, None, 0.0, False, res,
                                  lambda m: None)
    finally:
        sync.drums_were_read = saved
    assert any("has not cooked" in m for m in res.problems), res.problems


def test_a_driver_that_sees_no_hits_is_refused_differently():
    from lyricfield import preflight, sync

    cfg = Config()
    cfg.with_beat("punch")
    saved = sync.drums_were_read
    sync.drums_were_read = lambda client, container=None: {"kick": 0, "snare": 0}
    try:
        res = preflight.Result()
        preflight._beat_is_driven(FakeTD(), cfg, None, 0.0, False, res,
                                  lambda m: None)
    finally:
        sync.drums_were_read = saved
    assert any("no drum hits" in m for m in res.problems), res.problems


def test_no_beat_preset_means_nothing_to_check():
    """`none` is a legitimate choice and asks the driver for nothing."""
    from lyricfield import preflight, sync

    cfg = Config()
    cfg.with_beat("none")
    asked = []
    saved = sync.drums_were_read
    sync.drums_were_read = lambda client, container=None: asked.append(1)
    try:
        res = preflight.Result()
        preflight._beat_is_driven(FakeTD(), cfg, None, 0.0, False, res,
                                  lambda m: None)
    finally:
        sync.drums_were_read = saved
    assert res.problems == [] and not asked
