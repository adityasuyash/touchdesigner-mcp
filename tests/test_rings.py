"""Rings: the beat as circles leaving the centre.

The first beatsync renderer here whose Script TOP *is* the picture -- it runs at
frame resolution and writes pixels, where `pulse_grid` and `swell` run at one
pixel per grid cell and let Text TOPs draw glyphs. There is no lattice in it.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.types.rings import params as P


@pytest.fixture
def rg():
    src = types_mod.get_type("rings").field_source()
    mod = pytypes.ModuleType("rings_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    mod.S.clear()
    return mod


# ----------------------------------------------------------------- the type

def test_it_is_a_beatsync_type_needing_only_drums():
    vt = types_mod.get_type("rings")
    assert vt.family == types_mod.BEATSYNC
    assert vt.needs_lyrics is False
    assert types_mod.DRUMS in vt.needs


def test_it_does_not_borrow_the_grid_renderer():
    from pathlib import Path
    here = Path(types_mod.__file__).parent / "rings"
    for name in ("build.py", "params.py", "field.py"):
        assert "from ..lyric_grid" not in (here / name).read_text()


def test_it_declares_no_grid_vocabulary():
    p = P.Params()
    names = {f for sec in p.__dataclass_fields__
             for f in getattr(p, sec).__dataclass_fields__}
    assert not (names & {"cols", "vrows", "band", "band_top", "glyphs"}), names


# ------------------------------------------------------------- the geometry

def test_the_radius_grid_is_built_once_and_reused(rg):
    """It is the whole reason a pixel renderer is affordable: the expensive
    arrays never change, so a frame is a few broadcasts over them."""
    r1, a1 = rg._grids()
    r2, a2 = rg._grids()
    assert r1 is r2 and a1 is a2


def test_radius_is_zero_at_the_centre_and_grows_outward(rg):
    r, _ = rg._grids()
    h, w = r.shape
    assert r[h // 2, w // 2] < 0.01
    assert r[0, 0] > r[h // 2, w // 2]


def test_the_field_is_portrait_shaped(rg):
    r, _ = rg._grids()
    h, w = r.shape
    assert h > w, "a 720x1280 frame should give a taller field than it is wide"


# ------------------------------------------------------------------- a ring

def test_a_kick_is_born_as_a_circle_not_a_point(rg):
    """Born at zero radius a ring is a dot at the centre, which reads as a
    flash rather than as something leaving."""
    rg.S['rings'] = [10.0]
    out = rg._rings(10.0)
    r, _ = rg._grids()
    h, w = out.shape
    assert out[h // 2, w // 2] < out.max(), (
        "the brightest point is the centre, so this is a flash not a ring")


def test_a_ring_travels_outward(rg):
    """The radius of the brightest pixel should grow with time."""
    def peak_radius(t):
        rg.S['rings'] = [10.0]
        out = rg._rings(t)
        r, _ = rg._grids()
        return float(r[np.unravel_index(np.argmax(out), out.shape)])
    assert peak_radius(10.2) < peak_radius(10.5) < peak_radius(10.8)


def test_a_ring_fades_and_is_forgotten(rg):
    rg.DECAY = 0.5
    rg.S['rings'] = [10.0]
    assert rg._rings(10.1).max() > 0
    rg._rings(11.0)
    assert rg.S['rings'] == [], "a dead ring is still being carried"


def test_only_so_many_rings_are_kept(rg):
    """A long song is thousands of kicks; the field must not accumulate them."""
    rg.LIMIT = 4
    rg.DECAY = 1e6
    rg.S['rings'] = [float(i) for i in range(50)]
    rg._rings(60.0)
    assert len(rg.S['rings']) <= 4


# ------------------------------------------------ envelopes, clamped at both ends

def test_a_strike_ahead_of_the_playhead_cannot_blow_the_field_out(rg):
    """`1 - (t - struck) / decay` is greater than one whenever the strike is
    ahead of `t`, and grows without limit as the gap widens. A seek makes that
    routine.

    Measured while this was being written: the field's mean reached 0.86 of
    white, a flat glare with the rings invisible inside it. The same unclamped
    shape was already in `pulse_grid` and `swell`.
    """
    rg.S['snare_t'] = 100.0          # a snare a long way ahead of now
    out = rg._spokes(10.0)
    assert out.max() <= rg.PEAK + 1e-6, (
        f"the snare envelope exceeded its own peak: {out.max()}")
    rg.S['high_t'] = 100.0
    assert rg._grain(10.0).max() <= rg.LIFT + 1e-6


def test_a_ring_ahead_of_the_playhead_is_ignored(rg):
    rg.S['rings'] = [100.0]
    assert rg._rings(10.0).max() == pytest.approx(0.0)


# -------------------------------------------------------------- the defaults

def test_the_defaults_are_a_valid_config():
    assert P.Params().validate() == []


def test_two_sections_never_share_a_tunable_name():
    """`flatten()` merges every section into one dict, so a shared key means
    the later section silently wins. `decay` was in three of them."""
    p = P.Params()
    seen = {}
    for sec in p.__dataclass_fields__:
        for f in getattr(p, sec).__dataclass_fields__:
            assert f not in seen, f"{f} in both {seen.get(f)} and {sec}"
            seen[f] = sec
