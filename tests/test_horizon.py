"""Horizon: a neon grid running to a banded sun.

The only renderer here that draws a *place* rather than a pattern over black,
and the only one with two hues in a single frame.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.types.horizon import params as P


@pytest.fixture
def hz():
    src = types_mod.get_type("horizon").field_source()
    mod = pytypes.ModuleType("horizon_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    mod.S.clear()
    return mod


def test_it_is_a_lyric_type_that_also_answers_the_drums():
    vt = types_mod.get_type("horizon")
    assert vt.family == types_mod.LYRIC
    assert vt.needs_lyrics is True
    assert types_mod.DRUMS in vt.needs


def test_it_does_not_borrow_the_grid_renderer():
    from pathlib import Path
    here = Path(types_mod.__file__).parent / "horizon"
    for name in ("build.py", "params.py", "field.py"):
        assert "from ..lyric_grid" not in (here / name).read_text()


# ------------------------------------------------------------- the scene

def test_the_sun_sits_on_the_horizon_and_not_over_the_floor(hz):
    """A sun painted over the floor is not a horizon, it is a shape in front
    of one. The first render ran the disc all the way down the frame."""
    v, hue = hz._scene(1.0, 0.0)
    x, y = hz._grids()
    h, w = hz.S['shape']
    row_below = int(h * min(0.99, hz.HORIZON + 0.25))
    # Below the horizon the hue must be the cold one -- the floor's -- with no
    # trace of the sun's.
    assert abs(float(hue[row_below, w // 2]) - hz.COLD) < 1e-5


def test_the_sun_is_round_not_stretched(hz):
    """In 0..1 coordinates a step in y covers `height` pixels and a step in x
    covers `width`, so y is the axis that must be scaled to make a circle.
    Inverted, the sun came out as a tall ellipse running the whole frame."""
    v, hue = hz._scene(1.0, 0.0)
    x, y = hz._grids()
    h, w = hz.S['shape']
    sun = (hue == hz.HOT) & (v > hz.FLOOR + 1e-6)
    rows = np.where(sun.any(axis=1))[0]
    cols = np.where(sun.any(axis=0))[0]
    assert len(rows) and len(cols), "no sun was drawn at all"
    # Its extent in pixels should be comparable in both axes.
    tall = (rows[-1] - rows[0]) / float(h) * hz.HEIGHT
    wide = (cols[-1] - cols[0]) / float(w) * hz.WIDTH
    assert 0.5 < tall / wide < 1.6, f"sun is {tall:.0f}x{wide:.0f} px"


def test_the_floor_runs_in_perspective(hz):
    """Rungs must bunch toward the horizon: the gap between them near the
    viewer is larger than the gap near the horizon. A skewed grid does not do
    this and reads as wallpaper."""
    v, _ = hz._scene(1.0, 0.0)
    x, y = hz._grids()
    h, w = hz.S['shape']
    col = v[:, w // 2]
    below = int(h * hz.HORIZON) + 2
    near = col[int(h * 0.95):]
    far = col[below:below + max(2, int(h * 0.05))]
    assert near.std() < far.std() or near.mean() > far.mean()


def test_the_floor_moves(hz):
    a, _ = hz._scene(1.0, 0.0)
    b, _ = hz._scene(1.4, 0.0)
    assert not np.allclose(a, b)


def test_a_kick_brightens_the_floor(hz):
    quiet, _ = hz._scene(1.0, 0.0)
    struck, _ = hz._scene(1.0, 1.0)
    assert struck.mean() > quiet.mean()


def test_two_hues_are_in_one_frame(hz):
    """The look is built on the collision of a hot colour and a cold one; a
    single hue cannot make it."""
    _, hue = hz._scene(1.0, 0.0)
    assert len(np.unique(np.round(hue, 3))) > 1


# ------------------------------------------------------------- the defaults

def test_the_defaults_are_a_valid_config():
    assert P.Params().validate() == []


def test_two_hues_that_are_nearly_the_same_are_pushed_apart():
    p = P.Params()
    p.look.hot, p.look.cold = 0.5, 0.52
    P.reconcile(p)
    assert abs(p.look.hot - p.look.cold) >= 0.12
    assert p.validate() == []


def test_two_sections_never_share_a_tunable_name():
    """`size` was in both `sun` and `line`, which also made one RANGES entry
    serve two different meanings."""
    p = P.Params()
    seen = {}
    for sec in p.__dataclass_fields__:
        for f in getattr(p, sec).__dataclass_fields__:
            assert f not in seen, f"{f} in both {seen[f]} and {sec}"
            seen[f] = sec
