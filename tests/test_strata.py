"""Strata: the beat as solid bands, played one at a time.

The straight, stacked, hard-edged answer to `rings`. Two beat renderers a
viewer could confuse would be two renderers doing one job.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.types.strata import params as P


@pytest.fixture
def st():
    src = types_mod.get_type("strata").field_source()
    mod = pytypes.ModuleType("strata_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    mod.S.clear()
    return mod


def test_it_is_a_beatsync_type_needing_only_drums():
    vt = types_mod.get_type("strata")
    assert vt.family == types_mod.BEATSYNC
    assert vt.needs_lyrics is False


def test_it_does_not_borrow_the_grid_renderer():
    from pathlib import Path
    here = Path(types_mod.__file__).parent / "strata"
    for name in ("build.py", "params.py", "field.py"):
        assert "from ..lyric_grid" not in (here / name).read_text()


# --------------------------------------------------------------- the stack

def test_the_gap_is_geometry_not_brightness(st):
    """The dark between bands is what makes them read as bars rather than as
    one gradient, so it is a hole in the field and not a dim patch."""
    idx, ink = st._band_index()
    assert set(np.unique(ink)) <= {0.0, 1.0}, "the gap has soft edges"
    assert 0.0 in np.unique(ink), "there is no gap at all"


def test_every_row_belongs_to_a_band(st):
    idx, _ = st._band_index()
    assert idx.min() >= 0
    assert idx.max() == st.COUNT - 1


def test_an_unstruck_band_sits_at_rest(st):
    st.S['struck'] = {}
    assert st._levels(5.0) == [pytest.approx(st.REST)] * st.COUNT


def test_a_struck_band_is_brighter_and_falls_back(st):
    st.DECAY = 0.5
    st.S['struck'] = {2: 10.0}
    now = st._levels(10.0)
    later = st._levels(10.3)
    settled = st._levels(11.0)
    assert now[2] == pytest.approx(st.LIT)
    assert st.REST < later[2] < st.LIT
    assert settled[2] == pytest.approx(st.REST)


def test_only_the_struck_band_moves(st):
    st.S['struck'] = {2: 10.0}
    levels = st._levels(10.0)
    assert levels[2] > levels[0] == pytest.approx(st.REST)


def test_a_strike_ahead_of_the_playhead_does_not_blow_a_band_out(st):
    """The uncapped-envelope defect, which `rings` found the hard way."""
    st.S['struck'] = {1: 100.0}
    assert st._levels(10.0)[1] == pytest.approx(st.REST)


# ------------------------------------------------------------- the defaults

def test_the_defaults_are_a_valid_config():
    assert P.Params().validate() == []


def test_a_kick_cannot_darken_its_own_band():
    p = P.Params()
    p.band.rest, p.band.lit = 0.9, 0.2
    P.reconcile(p)
    assert p.band.rest < p.band.lit


def test_a_struck_band_keeps_its_brightness_when_the_stack_gives_way():
    """The hats give way, then the glow. The struck band is the thing the
    renderer is for."""
    p = P.Params()
    p.band.lit, p.flicker.lift, p.look.glow = 0.98, 0.5, 0.9
    P.reconcile(p)
    assert p.validate() == [], p.validate()
    assert p.band.lit == pytest.approx(0.98)


def test_two_sections_never_share_a_tunable_name():
    p = P.Params()
    seen = {}
    for sec in p.__dataclass_fields__:
        for f in getattr(p, sec).__dataclass_fields__:
            assert f not in seen, f"{f} in both {seen[f]} and {sec}"
            seen[f] = sec
