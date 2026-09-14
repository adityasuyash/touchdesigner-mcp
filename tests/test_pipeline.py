"""Ingest: what it measures, what it saves, and what it says out loud.

`pipeline.prepare` owns the resumability contract and writes every measured fact
the renderers and the UI later read. It had no test at all, which is how a whole
control came to be wired to a number that was never once written.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lyricfield import analysis as analysis_mod
from lyricfield import pipeline
from lyricfield import separate as separate_mod
from lyricfield import transcribe as transcribe_mod
from lyricfield.config import Config
from lyricfield.types import CUES, DRUMS, INSTRUMENTAL


class FakeStems:
    """What `separate.separate` hands back, without running Demucs."""

    def __init__(self, root: Path):
        self.vocals = root / "vocals.wav"
        self.instrumental = root / "no_vocals.wav"
        self.rhythm = root / "drums.wav"
        self.exists = True
        for p in (self.vocals, self.instrumental, self.rhythm):
            p.write_bytes(b"")


class FakeAnalysis:
    duration = 180.0
    hold_windows = [(0.0, 1.0)]
    kick_in = 8.0
    high_in = 20.0
    beat_period = 0.5
    beat_anchor = 0.25
    level = 0.3

    def __init__(self, hits=True):
        self._hits = hits

    def drum_table(self):
        from lyricfield.drums import DrumTable
        if not self._hits:
            return DrumTable.from_detection({"kick": [], "snare": [], "hat": []})
        return DrumTable.from_detection(
            {"kick": [1.0, 2.0], "snare": [1.5], "hat": [1.25, 1.75]})

    def to_dict(self):
        return {"duration": self.duration}


@pytest.fixture
def ingest(tmp_path, monkeypatch):
    """`prepare` with Demucs, Groq and the analyser all replaced."""
    src = tmp_path / "song.wav"
    src.write_bytes(b"")
    stems = FakeStems(tmp_path)
    state = {"vocal_entry_calls": 0, "analysis": FakeAnalysis()}

    monkeypatch.setattr(separate_mod, "separate",
                        lambda *a, **k: stems)
    monkeypatch.setattr(analysis_mod, "analyse",
                        lambda *a, **k: state["analysis"])
    monkeypatch.setattr(analysis_mod, "missed_windows", lambda *a, **k: [])

    def vocal_entry(path):
        state["vocal_entry_calls"] += 1
        return 12.5
    monkeypatch.setattr(analysis_mod, "vocal_entry", vocal_entry)

    def transcribe_to_cues(*a, **k):
        from lyricfield.cues import Cue, CueTable
        return CueTable([Cue(word="hello", start=30.0, line=1)])
    monkeypatch.setattr(transcribe_mod, "transcribe_to_cues", transcribe_to_cues)

    def run(**kw):
        kw.setdefault("track", src)
        kw.setdefault("config_path", tmp_path / "config.toml")
        kw.setdefault("cues_path", tmp_path / "cues.tsv")
        kw.setdefault("drums_path", tmp_path / "drums.tsv")
        kw.setdefault("stem_root", tmp_path / "stems")
        kw.setdefault("groq_key", "not-used")
        return pipeline.prepare(**kw), kw
    run.state = state
    run.tmp = tmp_path
    return run


# ------------------------------------------------- the measured vocal entry

def test_the_measured_vocal_entry_reaches_the_saved_config(ingest):
    """It was measured 58 lines after the config was written, so the value the
    UI reads was the `0.0` it was initialised with -- every time, on every song.

    "Start before the vocals" is wired to exactly this number. For a lyric song
    it silently degraded to the first cue, which `config.py` calls the
    untrustworthy value this measurement exists to replace; for a beatsync song
    the button could never work at all.
    """
    out, kw = ingest()
    assert out.vocal_in == pytest.approx(12.5)
    saved = Config.load(kw["config_path"])
    assert saved.track.vocal_in == pytest.approx(12.5), (
        "the vocal entry was measured but never reached the config the UI reads")


def test_the_vocal_entry_is_measured_even_with_no_cues(ingest):
    """It is a fact about the vocal stem, not about the words. It used to be
    measured inside the branch that checks transcription for dropped lines, so
    a song with no cue table never got one."""
    out, kw = ingest(needs=frozenset({INSTRUMENTAL, DRUMS}))
    assert out.vocal_in == pytest.approx(12.5)
    assert Config.load(kw["config_path"]).track.vocal_in == pytest.approx(12.5)


def test_the_vocal_entry_is_measured_once(ingest):
    """It decodes the vocal stem; doing it twice per run is waste."""
    ingest()
    assert ingest.state["vocal_entry_calls"] == 1


# ------------------------------------------------------ what ingest reports

def test_a_drum_table_with_no_hits_is_reported_as_a_problem(ingest):
    """`DrumTable.problems()` opens with "no drum hits were detected at all"
    and was called from nowhere in the package. Every renderer answers the
    drums, so a table with none is a beatsync video that never moves -- and it
    was announced as "0 kicks, 0 snares, 0 hats" and counted as success.
    """
    ingest.state["analysis"] = FakeAnalysis(hits=False)
    out, _ = ingest()
    said = " ".join(out.warnings + out.problems)
    assert "drum" in said.lower(), (
        f"an empty drum table was not reported; warnings={out.warnings} "
        f"problems={out.problems}")


def test_a_drum_table_with_hits_is_not_reported(ingest):
    out, _ = ingest()
    assert not [w for w in out.warnings if "no drum hits" in w]


def test_the_measured_facts_reach_the_config(ingest):
    """Everything the renderers read comes through here."""
    _, kw = ingest()
    t = Config.load(kw["config_path"]).track
    assert t.duration == pytest.approx(180.0)
    assert t.kick_in == pytest.approx(8.0)
    assert t.high_in == pytest.approx(20.0)
    assert t.beat_period == pytest.approx(0.5)
    assert t.level == pytest.approx(0.3)
