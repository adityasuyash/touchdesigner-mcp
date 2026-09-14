"""Spectrum: the beat as bars.

What separates a spectrum analyser from a row of blocks that jump is entirely in
the dynamics: bars rise instantly and fall slowly, and each carries a cap that
marks its recent peak and falls back on its own. Both are easy to get backwards
in ways that still produce a moving picture, so both are pinned here.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.config import Config
from lyricfield.types.spectrum import params as P
from lyricfield.types.spectrum.build import network


@pytest.fixture
def sp():
    src = types_mod.get_type("spectrum").field_source()
    mod = pytypes.ModuleType("spectrum_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    mod._apply_params()
    return mod


# ----------------------------------------------------------------- the type

def test_it_is_a_beatsync_type_that_needs_no_words():
    vt = types_mod.get_type("spectrum")
    assert vt.family == types_mod.BEATSYNC
    assert vt.needs_lyrics is False


def test_it_is_the_only_type_that_needs_the_band_table():
    """Every other renderer answers onsets, which the drum table already
    carries. Asking for the spectrum when you do not draw one would make every
    song fail preflight for data nothing reads."""
    want = [t.slug for t in types_mod.list_types()
            if types_mod.BANDS in t.needs]
    assert want == ["spectrum"], want


# ------------------------------------------------------------- the dynamics

def test_a_bar_rises_instantly(sp):
    """A bar chart exists to show transients; a slow rise misses every one."""
    assert sp._settle(0.1, 0.9, dt=1 / 60.0, seconds=0.2) == pytest.approx(0.9)


def test_a_bar_falls_over_the_settle_time(sp):
    half = sp._settle(1.0, 0.0, dt=0.1, seconds=0.2)
    assert 0.0 < half < 1.0
    assert half == pytest.approx(0.5)


def test_a_bar_never_falls_below_the_measurement(sp):
    assert sp._settle(1.0, 0.4, dt=10.0, seconds=0.2) == pytest.approx(0.4)


def test_no_settle_time_means_the_bar_simply_follows(sp):
    assert sp._settle(1.0, 0.2, dt=0.1, seconds=0.0) == pytest.approx(0.2)


def test_a_cap_holds_at_a_new_peak_then_falls(sp):
    sp.HANG, sp.FALL = 0.2, 1.0
    caps = sp._caps([], [0.8], dt=1 / 60.0)
    assert caps[0][0] == pytest.approx(0.8)
    # while it hangs, it does not move
    held = sp._caps(caps, [0.1], dt=0.1)
    assert held[0][0] == pytest.approx(0.8)
    # once the hang is spent, it falls
    for _ in range(4):
        held = sp._caps(held, [0.1], dt=0.1)
    assert held[0][0] < 0.8


def test_a_cap_never_falls_below_its_bar(sp):
    sp.HANG, sp.FALL = 0.0, 10.0
    caps = sp._caps([(0.9, 0.0)], [0.5], dt=1.0)
    assert caps[0][0] == pytest.approx(0.5)


# ------------------------------------------------------------- the folding

def test_more_bands_than_bars_are_averaged_rather_than_sampled(sp):
    """Taking every Nth band throws away whatever fell between, which on a
    narrow frame is most of the spectrum."""
    folded = sp._fold([0.0, 1.0, 0.0, 1.0], 2)
    assert folded == pytest.approx([0.5, 0.5])


def test_matching_counts_pass_straight_through(sp):
    assert sp._fold([0.2, 0.4, 0.6], 3) == pytest.approx([0.2, 0.4, 0.6])


def test_no_measurement_folds_to_silence(sp):
    assert sp._fold([], 5) == [0.0] * 5


def test_fewer_bands_than_bars_still_fills_every_bar(sp):
    out = sp._fold([0.5, 1.0], 6)
    assert len(out) == 6
    assert all(v > 0 for v in out)


# ------------------------------------------------------- reading the table

def test_the_levels_are_looked_up_by_time(sp):
    times = [0.0, 1.0]
    rows = [(0.0,), (1.0,)]
    assert sp._bands_at(times, rows, 0.5)[0] == pytest.approx(0.5)


def test_a_song_with_no_band_table_survives(sp):
    """A song ingested before the spectrum existed has none, and the renderer
    must not raise -- it draws nothing and says so through its stats."""
    assert sp._bands_at([], [], 1.0) == ()
    assert sp._fold(sp._bands_at([], [], 1.0), 8) == [0.0] * 8


# ---------------------------------------------------- where in the song

def test_it_opens_arrives_and_ends(sp):
    sp.KICK_IN, sp.HIGH_IN, sp.TAIL_END = 20.0, 40.0, 200.0
    sp.INTRO_OPEN, sp.ARRIVE, sp.OUTRO = 0.3, 0.85, 10.0
    assert sp._section_gain(5.0) < sp._section_gain(30.0) < sp._section_gain(60.0)
    assert sp._section_gain(199.5) < sp._section_gain(150.0)


# ---------------------------------------------------------------- the network

def test_the_band_table_is_in_the_network():
    specs = {s.name: s for s in network(Config(type="spectrum"))}
    assert specs["bands"].type == "tableDAT"
    assert specs["bands"].preserve, (
        "a rebuild must not wipe the measured spectrum")


def test_the_bars_are_scaled_up_without_being_smoothed():
    """A bar's edge is the whole point of a bar; interpolating it up turns the
    chart into a soft heightmap."""
    specs = {s.name: s for s in network(Config(type="spectrum"))}
    assert specs["sp_up"].params["inputfiltertype"] == "nearest"


# ------------------------------------------------------------- the defaults

def test_the_defaults_are_a_valid_config():
    assert P.Params().validate() == []


def test_mirrored_bars_at_the_bottom_of_the_frame_are_refused():
    """Half of a mirrored bar grows downward, so a baseline on the floor puts
    it off the frame entirely."""
    p = P.Params()
    p.bars.mirror, p.bars.floor_at = True, 0.95
    assert any("mirrored" in m for m in p.validate())
    P.reconcile(p)
    assert p.validate() == [], p.validate()
    assert p.bars.floor_at == pytest.approx(0.5)


def test_the_stack_stays_under_white():
    p = P.Params()
    p.look.peak, p.look.floor = 0.99, 0.2
    P.reconcile(p)
    assert p.validate() == [], p.validate()
    assert p.look.peak == pytest.approx(0.99)


def test_no_two_sections_share_a_key():
    import collections
    p = P.Params()
    names = [f for sec in p.__dataclass_fields__
             for f in getattr(p, sec).__dataclass_fields__]
    dupes = [k for k, n in collections.Counter(names).items() if n > 1]
    assert not dupes, dupes
