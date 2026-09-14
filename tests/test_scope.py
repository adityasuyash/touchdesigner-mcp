"""Scope: one continuous curve with a phosphor trail.

The third beat renderer: `rings` is soft and radial, `strata` hard and stacked,
this a single bright line on black that reads as an instrument.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.types.scope import params as P


@pytest.fixture
def sc():
    src = types_mod.get_type("scope").field_source()
    mod = pytypes.ModuleType("scope_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    mod.S.clear()
    return mod


def test_it_is_a_beatsync_type_needing_only_drums():
    vt = types_mod.get_type("scope")
    assert vt.family == types_mod.BEATSYNC
    assert vt.needs_lyrics is False


def test_it_does_not_borrow_the_grid_renderer():
    from pathlib import Path
    here = Path(types_mod.__file__).parent / "scope"
    for name in ("build.py", "params.py", "field.py"):
        assert "from ..lyric_grid" not in (here / name).read_text()


# ------------------------------------------------------------- determinism

def test_a_frame_depends_only_on_its_own_timestamp(sc):
    """The trail is drawn from the curve's own past rather than accumulated in
    a buffer. That is the difference between a renderer that re-renders
    identically and one that only looks right if you watched it get there --
    and it is why this renderer needs no Feedback TOP and no reset.
    """
    straight = sc._draw(9.0, 0.0, 1.0)
    sc.S.clear()
    for t in (1.0, 3.0, 5.0, 7.0):     # arrive via a different history
        sc._draw(t, 0.4, 1.0)
    after = sc._draw(9.0, 0.0, 1.0)
    assert np.array_equal(straight, after)


def test_seeking_gives_the_same_frame_as_playing_to_it(sc):
    a = sc._draw(12.34, 0.2, 0.8)
    b = sc._draw(12.34, 0.2, 0.8)
    assert np.array_equal(a, b)


# ----------------------------------------------------------------- the curve

def test_the_head_is_brighter_than_the_tail(sc):
    """A phosphor trail that is uniform is a wire, not a trail."""
    x, y = sc._curve(np.array([0.0], np.float32), 0.0)
    field = sc._draw(0.0, 0.0, 1.0)
    h, w = field.shape
    head = field[int(y[0] * (h - 1)), int(x[0] * (w - 1))]
    assert head > 0.0
    assert head >= field.mean() * 4


def test_the_curve_stays_inside_the_frame(sc):
    ts = np.linspace(0.0, 20.0, 400, dtype=np.float32)
    x, y = sc._curve(ts, 1.0)
    assert x.min() >= 0.0 and x.max() <= 1.0
    assert y.min() >= 0.0 and y.max() <= 1.0


def test_the_figure_is_the_same_shape_whatever_the_frame_is(sc):
    """Aspect-corrected against the smaller side. Uncorrected, a circle comes
    out an oval -- which happened twice already in this pass."""
    ts = np.linspace(0.0, 8.0, 300, dtype=np.float32)
    sc.FREQX = sc.FREQY = 2.0     # equal frequencies trace a line at 45 degrees
    x, y = sc._curve(ts, 0.0)
    wide = (x.max() - x.min()) * sc.WIDTH
    tall = (y.max() - y.min()) * sc.HEIGHT
    assert 0.85 < tall / wide < 1.18, f"{tall:.0f} x {wide:.0f} px"


def test_a_kick_changes_the_figure_not_just_its_brightness(sc):
    """Brightening on the beat is what every other renderer does. This one
    bends the shape, which is the thing an oscilloscope can do that they
    cannot."""
    plain = sc._draw(4.0, 0.0, 1.0)
    bent = sc._draw(4.0, 0.6, 1.0)
    assert not np.array_equal(plain, bent)


def test_the_trail_is_drawn_with_one_scatter_not_a_loop(sc):
    """`np.add.at` accumulates where samples land on the same pixel, which is
    what makes the slow parts of the figure brighter -- exactly what a phosphor
    screen does."""
    field = sc._draw(3.0, 0.0, 1.0)
    assert field.max() > sc.WEIGHT * 0.9


# ------------------------------------------------------------- the defaults

def test_the_defaults_are_a_valid_config():
    assert P.Params().validate() == []


def test_equal_frequencies_are_refused_and_repaired():
    """Two sines at the same frequency draw a straight line, not a figure."""
    p = P.Params()
    p.curve.freqx = p.curve.freqy = 3.0
    assert p.validate() != []
    P.reconcile(p)
    assert p.validate() == []


def test_too_few_samples_is_refused():
    p = P.Params()
    p.trail.samples = 3
    assert any("samples" in m for m in p.validate())


def test_two_sections_never_share_a_tunable_name():
    p = P.Params()
    seen = {}
    for sec in p.__dataclass_fields__:
        for f in getattr(p, sec).__dataclass_fields__:
            assert f not in seen, f"{f} in both {seen[f]} and {sec}"
            seen[f] = sec
