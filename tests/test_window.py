"""Window: the words are a hole, and light moves behind them.

The only renderer where the lyric half and the beat half are one picture. A
Matte TOP composites the moving field through the type, so what you read is
letterforms and what you watch move is the drums.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.types.window import params as P


@pytest.fixture
def win():
    src = types_mod.get_type("window").field_source()
    mod = pytypes.ModuleType("window_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    mod.S.clear()
    return mod


def test_it_needs_both_words_and_drums():
    """Which is the point of it: every other type is one or the other."""
    vt = types_mod.get_type("window")
    assert vt.needs_lyrics is True
    assert types_mod.DRUMS in vt.needs
    assert vt.family == types_mod.LYRIC


def test_it_does_not_borrow_the_grid_renderer():
    from pathlib import Path
    here = Path(types_mod.__file__).parent / "window"
    for name in ("build.py", "params.py", "field.py"):
        assert "from ..lyric_grid" not in (here / name).read_text()


# ------------------------------------------------------------ lines, not words

def test_words_are_grouped_into_lines(win):
    """This renderer's subject is something you read, so it shows a line at a
    time where `monument` shows a word at a time."""
    rows = [("every", 1.0, 1), ("word", 1.4, 1), ("finds", 1.8, 1),
            ("then", 3.0, 2), ("fades", 3.4, 2)]
    win.S['lines'] = [(1.0, 1.8, "every word finds"), (3.0, 3.4, "then fades")]
    text, lit = win._line_at(win.S['lines'], 1.5)
    assert text == "every word finds"
    assert lit == pytest.approx(1.0)


def test_a_line_is_up_before_its_first_word(win):
    """Nothing should be a race to read."""
    win.LEAD, win.HOLD, win.FADE = 0.4, 0.5, 0.3
    lines = [(2.0, 3.0, "every word finds")]
    assert win._line_at(lines, 1.8)[1] == pytest.approx(1.0)
    assert win._line_at(lines, 1.5)[1] == pytest.approx(0.0)


def test_a_line_holds_then_fades(win):
    win.LEAD, win.HOLD, win.FADE = 0.4, 0.5, 0.4
    lines = [(2.0, 3.0, "a line")]
    assert win._line_at(lines, 3.4)[1] == pytest.approx(1.0)
    part = win._line_at(lines, 3.6)[1]
    assert 0.0 < part < 1.0
    assert win._line_at(lines, 4.0)[1] == pytest.approx(0.0)


def test_a_long_line_is_wrapped_without_splitting_a_word(win):
    out = win._wrap("every word finds its place", 12)
    assert "\n" in out
    for part in out.split("\n"):
        assert len(part) <= 12, part
    assert out.replace("\n", " ") == "every word finds its place"


def test_a_word_longer_than_the_wrap_is_left_whole(win):
    """Breaking mid-word would be worse than overflowing."""
    assert win._wrap("extraordinarily", 6) == "extraordinarily"


# -------------------------------------------------------------- the field

def test_the_field_moves(win):
    """If two moments look the same, there is nothing to see through the
    letters and the whole idea is lost."""
    a = win._field(1.0, 0.0, 0.0)
    b = win._field(1.6, 0.0, 0.0)
    assert not np.allclose(a, b)


def test_a_kick_brightens_the_whole_field(win):
    quiet = win._field(1.0, 0.0, 0.0)
    struck = win._field(1.0, 1.0, 0.0)
    assert struck.mean() > quiet.mean()


def test_the_grids_are_built_once(win):
    x1, y1 = win._grids()
    x2, y2 = win._grids()
    assert x1 is x2 and y1 is y2


# ------------------------------------------------------------- the defaults

def test_the_defaults_are_a_valid_config():
    assert P.Params().validate() == []


def test_the_light_behind_the_letters_keeps_its_brightness():
    """When the stack is too bright the kick gives way, not the light: the
    light is what is being read through."""
    p = P.Params()
    p.look.peak, p.field_.kick_push, p.field_.hat_grain = 0.98, 0.9, 0.4
    P.reconcile(p)
    assert p.validate() == [], p.validate()
    assert p.look.peak == pytest.approx(0.98)


def test_two_sections_never_share_a_tunable_name():
    p = P.Params()
    seen = {}
    for sec in p.__dataclass_fields__:
        for f in getattr(p, sec).__dataclass_fields__:
            assert f not in seen, f"{f} in both {seen[f]} and {sec}"
            seen[f] = sec
