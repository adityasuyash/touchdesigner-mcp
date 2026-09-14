"""Where a line of words sits.

For a long time there was exactly one answer: a snaking path from a random
start. Every lyric style used it, so no amount of colour, glow or timing made
two looks structurally different -- they were the same arrangement in a
different tint. Layout is the axis that separates them, and it was the one axis
nobody could reach.

The thing each mode must not do is fail to place a line. `_lay_line` returning
None means a word the song sings with nothing on screen lit, and nothing
reports it.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.types.lyric_grid.params import LAYOUTS

MODES = [k for k, _ in LAYOUTS]
LINES = [
    [("hold", 1.0), ("on", 1.6), ("to", 2.2), ("what", 2.8)],
    [("and", 4.0), ("let", 4.6), ("it", 5.2), ("go", 5.8)],
    [("some", 8.0), ("other", 8.6), ("morning", 9.2)],
    [("every", 11.0), ("word", 11.5), ("finds", 12.0), ("its", 12.4),
     ("place", 12.9), ("then", 13.5), ("fades", 14.1)],
]


@pytest.fixture
def lay():
    src = types_mod.get_type("lyric_grid").field_source()
    mod = pytypes.ModuleType("layout_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    return mod


@pytest.mark.parametrize("mode", MODES)
def test_every_layout_places_every_line(lay, mode):
    """A line that will not place is a word sung against nothing."""
    lay.LAYOUT = mode
    misses = 0
    for seed in range(30):
        rng = np.random.default_rng(seed)
        claimed = set()
        for words in LINES:
            got = lay._lay_line(words, claimed, rng, tries=1800)
            if got is None:
                misses += 1
                continue
            for cells in got.values():
                claimed.update(cells)
    assert misses == 0, f"{mode}: {misses} lines had nowhere to go"


@pytest.mark.parametrize("mode", MODES)
def test_every_layout_keeps_its_letters_inside_the_band(lay, mode):
    """Below the band must stay black -- the invariant that shipped broken
    three times."""
    lay.LAYOUT = mode
    rng = np.random.default_rng(3)
    claimed = set()
    for words in LINES:
        got = lay._lay_line(words, claimed, rng, tries=1800)
        assert got is not None
        for cells in got.values():
            for r, c in cells:
                assert lay.BAND_TOP <= r < lay.BAND_TOP + lay.BAND, f"{mode}: row {r}"
                assert 0 <= c < lay.COLS, f"{mode}: col {c}"
            claimed.update(cells)


@pytest.mark.parametrize("mode", MODES)
def test_every_layout_gives_each_letter_its_own_cell(lay, mode):
    """Two letters in one cell is one letter lost."""
    lay.LAYOUT = mode
    rng = np.random.default_rng(5)
    claimed, seen = set(), set()
    for words in LINES:
        got = lay._lay_line(words, claimed, rng, tries=1800)
        assert got is not None
        for wi, cells in got.items():
            assert len(set(cells)) == len(cells), f"{mode}: word {wi} overlaps itself"
            assert not (set(cells) & seen), f"{mode}: word {wi} lands on another"
            seen.update(cells)
            claimed.update(cells)


@pytest.mark.parametrize("mode", MODES)
def test_every_layout_returns_one_run_per_word(lay, mode):
    """`draw` indexes the result by word, so a mode that loses one drops it."""
    lay.LAYOUT = mode
    rng = np.random.default_rng(11)
    for words in LINES:
        got = lay._lay_line(words, set(), rng, tries=1800)
        assert got is not None
        assert set(got) == set(range(len(words))), mode
        for wi, (w, _t) in enumerate(words):
            assert len(got[wi]) == len(w), f"{mode}: {w!r} got {len(got[wi])} cells"


def test_the_layouts_actually_arrange_things_differently(lay):
    """Otherwise this is four names for one picture, which is what it was."""
    shapes = {}
    for mode in MODES:
        lay.LAYOUT = mode
        rng = np.random.default_rng(9)
        got = lay._lay_line(LINES[3], set(), rng, tries=1800)
        rows = {r for cells in got.values() for r, _ in cells}
        cols = {c for cells in got.values() for _, c in cells}
        shapes[mode] = (len(rows), len(cols))
    assert len(set(shapes.values())) >= 3, f"layouts collapse together: {shapes}"


def test_rows_centres_what_it_lays(lay):
    """The point of the mode: a viewer reads it left to right, centred."""
    lay.LAYOUT = "rows"
    rng = np.random.default_rng(2)
    got = lay._lay_line(LINES[0], set(), rng, tries=1800)
    assert got is not None
    cols = [c for cells in got.values() for _, c in cells]
    left, right = min(cols), lay.COLS - 1 - max(cols)
    assert abs(left - right) <= max(4, lay.COLS // 4), \
        f"not centred: {left} left, {right} right"


def test_an_unknown_layout_is_refused_by_validate():
    from lyricfield.types.lyric_grid.params import Params
    p = Params()
    p.cueing.layout = "spiral"
    assert any("layout" in m for m in p.validate())
