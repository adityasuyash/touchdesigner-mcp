"""Orbit: the line rides a curve, a character at a time.

The renderer that proves the lattice is gone. Every other lyric type places
glyphs where something structural put them -- a cell, a centred line, a wrapped
block -- and no parameter escapes that, because the structure IS the renderer.
This one gives each character its own coordinate through the Text TOP's
Specification DAT.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.types.orbit import params as P


@pytest.fixture
def ob():
    src = types_mod.get_type("orbit").field_source()
    mod = pytypes.ModuleType("orbit_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    mod.S.clear()
    return mod


def test_it_is_a_lyric_type():
    vt = types_mod.get_type("orbit")
    assert vt.family == types_mod.LYRIC
    assert vt.needs_lyrics is True


def test_it_does_not_borrow_the_grid_renderer():
    from pathlib import Path
    here = Path(types_mod.__file__).parent / "orbit"
    for name in ("build.py", "params.py", "field.py"):
        assert "from ..lyric_grid" not in (here / name).read_text()


# ------------------------------------------------------- the specification

def test_the_spec_has_one_row_per_visible_character(ob):
    """That is the whole mechanism: a table of x, y, text, one row each."""
    spec = ob._spec("ab cd", 0.0, 1.0)
    rows = spec.strip().split("\n")
    assert rows[0].split("\t") == ["x", "y", "text"]
    assert len(rows) == 1 + 4, "spaces should not be given a row"


def test_every_character_lands_inside_the_frame(ob):
    for shape in ("circle", "spiral", "wave", "lissajous"):
        ob.SHAPE = shape
        for row in ob._spec("every word finds its place", 3.0, 1.0).split("\n")[1:]:
            x, y, _ch = row.split("\t")
            assert 0 <= int(x) <= ob.WIDTH, f"{shape}: x={x}"
            assert 0 <= int(y) <= ob.HEIGHT, f"{shape}: y={y}"


def test_a_circle_is_round_in_pixels_not_in_the_unit_square(ob):
    """A curve written in 0..1 space is an ellipse on screen, because a step in
    x covers `width` pixels and a step in y covers `height`. Uncorrected, the
    circle came out as a tall oval running off the frame."""
    ob.SHAPE = "circle"
    pts = [ob._point(i / 40.0, 1.0) for i in range(40)]
    xs = [p[0] * ob.WIDTH for p in pts]
    ys = [p[1] * ob.HEIGHT for p in pts]
    wide = max(xs) - min(xs)
    tall = max(ys) - min(ys)
    assert 0.85 < tall / wide < 1.18, f"{tall:.0f} x {wide:.0f} px"


def test_an_open_path_keeps_the_line_in_reading_order(ob):
    """A closed path can carry the line round and round, so its parameter
    wraps. Wrapping an open one teleports a character from the end of the line
    back to the start, mid-word."""
    ob.SHAPE = "wave"
    rows = ob._spec("abcdefghij", 5.0, 1.0).split("\n")[1:]
    xs = [int(r.split("\t")[0]) for r in rows]
    assert xs == sorted(xs), "the line does not run left to right"


def test_a_closed_path_carries_the_line_round(ob):
    ob.SHAPE = "circle"
    a = ob._spec("abcdefghij", 0.0, 1.0)
    b = ob._spec("abcdefghij", 4.0, 1.0)
    assert a != b, "the curve does not turn"


def test_a_kick_pushes_the_curve_outward(ob):
    ob.SHAPE = "circle"
    small = ob._point(0.0, 1.0)
    big = ob._point(0.0, 1.3)
    assert abs(big[0] - 0.5) > abs(small[0] - 0.5)


def test_an_empty_line_still_writes_a_header(ob):
    """A spec DAT with no header is not an empty spec, it is a broken one."""
    assert ob._spec("", 0.0, 1.0).startswith("x\ty\ttext")


# ------------------------------------------------------------- the defaults

def test_the_defaults_are_a_valid_config():
    assert P.Params().validate() == []


def test_an_unknown_path_is_refused_and_repaired():
    p = P.Params()
    p.path.shape = "helix"
    assert p.validate() != []
    P.reconcile(p)
    assert p.validate() == []
    assert p.path.shape in [k for k, _ in P.PATHS]


def test_every_declared_path_actually_draws(ob):
    """A path in the menu that the field script does not know would fall back
    to a circle and quietly ignore the choice."""
    for shape, _hint in P.PATHS:
        ob.SHAPE = shape
        pts = {ob._point(i / 12.0, 1.0) for i in range(12)}
        assert len(pts) > 3, f"{shape} collapses to a point"


def test_two_sections_never_share_a_tunable_name():
    p = P.Params()
    seen = {}
    for sec in p.__dataclass_fields__:
        for f in getattr(p, sec).__dataclass_fields__:
            assert f not in seen, f"{f} in both {seen[f]} and {sec}"
            seen[f] = sec
