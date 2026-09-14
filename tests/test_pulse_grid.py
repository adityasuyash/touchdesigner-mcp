"""The beatsync type: a video for a song with no words.

Before this existed, an instrumental rendered a black frame for its entire
length -- the only renderer available drew the song's own words, and there were
none. The field script imports standalone for the same reason `lyric_grid`'s
does, so what it draws is testable with no TouchDesigner.
"""

from __future__ import annotations

import types as pytypes
from pathlib import Path

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.types.pulse_grid import params as P

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def pulse_mod():
    src = types_mod.get_type("pulse_grid").field_source()
    mod = pytypes.ModuleType("pulse_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    return mod


# ----------------------------------------------------------------- the type

def test_it_is_registered_as_a_beatsync_type():
    vt = types_mod.get_type("pulse_grid")
    assert vt.family == types_mod.BEATSYNC
    assert vt.needs_lyrics is False


def test_it_asks_for_drums_and_nothing_else():
    """It used to ask for the raw mix, to save the minutes separation costs.

    That was a false economy twice over: a kick detector on a full mix fires on
    the bassline (phase concentration 0.12 within the beat -- uniform), and
    demucs computes all four sources whatever you ask it for, so the drums stem
    was being produced and discarded on every separation anyway.
    """
    vt = types_mod.get_type("pulse_grid")
    assert types_mod.DRUMS in vt.needs
    assert vt.needs_separation
    assert types_mod.VOCALS not in vt.needs   # still no vocal to isolate
    assert types_mod.CUES not in vt.needs     # and still nothing to transcribe


def test_defaults_are_valid():
    assert P.Params().validate() == []


def test_it_measures_the_same_regions_as_the_lyric_type():
    """The band is where anything may be drawn and below it must stay black --
    the same invariant, so the same crops."""
    assert set(P.Params().regions()) == {"band", "lower"}


# ------------------------------------------------------------- validation

def test_an_empty_glyph_set_is_refused():
    p = P.Params()
    p.pulse.glyphs = ""
    assert p.validate() != []


def test_a_zero_wave_span_is_refused():
    """It divides the beat period."""
    p = P.Params()
    p.pulse.wave_beats = 0.0
    assert p.validate() != []


def test_a_threshold_nothing_can_reach_is_refused():
    """Otherwise the bold layer never fires and the field is uniformly dim."""
    p = P.Params()
    p.pulse.lit_at = p.look.ceil + p.pulse.wave_lift + 0.2
    assert p.validate() != []


def test_density_outside_zero_to_one_is_refused():
    p = P.Params()
    p.pulse.density = 1.6
    assert p.validate() != []


# --------------------------------------------------------------- the field

def test_the_fallback_defaults_are_not_a_song(pulse_mod):
    d = pulse_mod.DEFAULTS
    assert d["duration"] == 0.0
    assert d["kick_in"] == 0.0
    assert not d["hold_windows"]
    assert d["beat_period"] > 0, "a zero period divides by zero every frame"


def test_a_missing_params_dat_is_recorded(pulse_mod):
    pulse_mod._load_params()
    assert pulse_mod.PARAMS_MISSING is True


def test_the_glyph_field_is_scattered_and_bounded(pulse_mod):
    m = pulse_mod
    m.S["rng"] = np.random.default_rng(4)
    m._init()
    chars = m.S["chars"]
    assert chars.shape == (m.BAND, m.COLS)
    drawn = chars != " "
    # roughly the requested density, and never the whole grid
    assert 0.3 < drawn.mean() < 1.0
    for ch in set(chars.flatten()) - {" "}:
        assert ch in m.GLYPHS


def test_every_cell_carries_a_brightness_bias(pulse_mod):
    m = pulse_mod
    m.S["rng"] = np.random.default_rng(4)
    m._init()
    bias = m.S["bias"]
    assert bias.shape == (m.BAND, m.COLS)
    assert 0.0 <= bias.min() and bias.max() <= 1.0


def test_the_sweep_completes_one_pass_per_wave_span(pulse_mod):
    """The crest is timed to the measured beat grid so it lands with the track
    rather than drifting against it."""
    m = pulse_mod
    span = m.BEAT * m.WAVE_BEATS
    phase = lambda t: ((t - m.BEAT_ANCHOR) % span) / span
    assert phase(m.BEAT_ANCHOR) == pytest.approx(0.0)
    assert phase(m.BEAT_ANCHOR + span / 2) == pytest.approx(0.5, abs=0.01)
    assert phase(m.BEAT_ANCHOR + span) == pytest.approx(0.0, abs=0.01)


def test_hold_windows_freeze_the_beat_response(pulse_mod):
    """Digital silence is a splice point; the field holds its breath rather
    than firing ripples at nothing."""
    m = pulse_mod
    m.HOLD_WINDOWS = ((5.0, 8.0),)
    assert m._held(6.0) is True
    assert m._held(4.0) is False
    assert m._held(9.0) is False
