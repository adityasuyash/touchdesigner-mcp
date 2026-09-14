"""The field behind the words.

`lyric_grid` left about two thirds of the band black and nothing was allowed to
draw there, even though its beat response was already computed over the whole
grid every frame and then sampled only under the letters. This is that space --
and the whole point of it is that it must never compete with, obscure, or sit
between the words it is behind.

These run `onCook` through the `cooker` harness, which is the first coverage
the compose path has ever had.
"""

from __future__ import annotations

import numpy as np
import pytest

PULSE = dict(back_level=0.05, back_lift=0.045, back_wave=1.0, ambient_target=60)
SWELL = dict(back_level=0.05, back_lift=0.045, back_swell=1.0, ambient_target=0)
MODES = {"pulse": PULSE, "swell": SWELL}


def _drawn(grid):
    return {(r, c) for r, row in enumerate(grid)
            for c, ch in enumerate(row) if ch != " "}


# --------------------------------------------------------- it draws at all

@pytest.mark.parametrize("mode", sorted(MODES), ids=sorted(MODES))
def test_the_backdrop_fills_space_the_words_left_black(cooker, mode):
    plain = cooker(2.0)
    withbg = cooker(2.0, **MODES[mode])
    assert withbg["stats"]["backdrop"] > 0
    assert len(_drawn(withbg["dim"])) > len(_drawn(plain["dim"]))


def test_no_backdrop_is_the_renderer_exactly_as_it_was(cooker):
    """`back_level = 0` has to be bit-identical, or every song that exists
    changes the moment this section ships.

    It is not enough to skip the emit: the backdrop must draw no random numbers
    either, because one shared generator lays out the stanzas and moving its
    position moves every word on screen.
    """
    before = cooker(2.0)
    after = cooker(2.0, back_level=0.0, back_wave=1.0, back_swell=1.0)
    assert after["dim"] == before["dim"]
    assert after["lit"] == before["lit"]
    assert np.array_equal(after["rgb"], before["rgb"])
    assert np.array_equal(after["alpha"], before["alpha"])


# ------------------------------------------------- it never touches a word

@pytest.mark.parametrize("mode", sorted(MODES), ids=sorted(MODES))
@pytest.mark.parametrize("t", [1.2, 2.0, 4.3, 5.5, 9.0])
def test_the_backdrop_never_lands_on_a_lit_word(cooker, mode, t):
    r = cooker(t, **MODES[mode])
    lit = _drawn(r["lit"])
    assert lit, "no words on screen; the test would prove nothing"
    # A lit cell's dim character must still be blank or the word's own glyph --
    # never a backdrop glyph, which would composite additively underneath it.
    for (row, col) in lit:
        assert r["dim"][row][col] in (" ", r["lit"][row][col])


@pytest.mark.parametrize("mode", sorted(MODES), ids=sorted(MODES))
def test_the_backdrop_never_wedges_between_two_letters_of_a_word(cooker, mode):
    """Words are laid on every OTHER cell.

    `_lay_line` walks `2*len(word) - 1` steps and keeps the even ones, so the
    cells BETWEEN adjacent letters are claimed by nothing and drawn by nothing.
    A mask built only from what was drawn calls them free, and a backdrop glyph
    lands in the gap inside every word on screen, at the tightest pitch the
    grid has. The claimed set plus one cell of margin is what prevents it.
    """
    plain = cooker(3.0)
    word_cells = _drawn(plain["dim"]) | _drawn(plain["lit"])
    r = cooker(3.0, **MODES[mode])
    back = _drawn(r["dim"]) - word_cells - _drawn(r["lit"])
    intruders = [
        (row, col) for (row, col) in back
        if ((row, col - 1) in word_cells and (row, col + 1) in word_cells)
        or ((row - 1, col) in word_cells and (row + 1, col) in word_cells)
    ]
    assert not intruders, f"backdrop glyphs inside words at {sorted(intruders)[:6]}"


def test_the_backdrop_stays_inside_the_band(cooker, field_mod):
    """Below the band must stay black -- the check that shipped as a bug three
    times over."""
    m = field_mod
    r = cooker(2.0, **PULSE)
    for row, line in enumerate(r["dim"]):
        if row < m.BAND_TOP or row >= m.BAND_TOP + m.BAND:
            assert set(line) <= {" "}, f"row {row} drawn outside the band"


# ------------------------------------------------------- it stays dimmer

@pytest.mark.parametrize("mode", sorted(MODES), ids=sorted(MODES))
def test_the_backdrop_never_outshines_the_dimmest_letter(cooker, field_mod, mode):
    """The constraint that makes this safe without depending on taste: it is
    bounded by `level_min`, so nothing in it can reach the brightness of the
    faintest letter of a word."""
    m = field_mod
    peak = 0.0
    for t in (1.0, 2.4, 3.7, 5.1, 8.8):
        r = cooker(t, kick=1.0, snare=1.0, high=1.0, **MODES[mode])
        words = _drawn(r["lit"]) | _drawn(cooker(t)["dim"])
        v = r["rgb"].max(axis=2)
        mask = np.ones(v.shape, bool)
        for (row, col) in words:
            mask[row, col] = False
        peak = max(peak, float(v[mask].max()))
    assert peak <= m.BACK_LEVEL + m.BACK_LIFT + 1e-6, f"backdrop reached {peak}"
    assert m.BACK_LEVEL + m.BACK_LIFT <= m.LEVEL_MIN


# ------------------------------------------------------- it answers the beat

def test_the_backdrop_answers_the_kick(cooker, field_mod):
    """Against `_backdrop` directly rather than the whole frame.

    Comparing two cooks with and without a kick does not work and the reason is
    worth recording: inserting a ring draws two integers from the shared
    generator, which shifts every per-letter brightness drawn afterwards, so the
    frame total moves for reasons that have nothing to do with the ripple. The
    pure function takes the ripple array as an argument and has none of that.
    """
    m = field_mod
    cooker(2.0, **PULSE)                       # bind the params, lay a field
    free = np.zeros((m.VROWS, m.COLS), bool)
    free[m.BAND_TOP:m.BAND_TOP + m.BAND, :] = True
    flat = np.zeros((m.VROWS, m.COLS), np.float32)

    quiet = m._backdrop(2.0, free, flat, flat, False)
    ring = flat.copy()
    ring[10:14, 8:12] = m.RIPPLE_LIFT          # a kick under those cells
    loud = m._backdrop(2.0, free, ring, flat, False)

    assert loud.sum() > quiet.sum()
    assert loud[10:14, 8:12].max() > quiet[10:14, 8:12].max()
    # and only where the kick actually was
    elsewhere = np.ones(flat.shape, bool)
    elsewhere[10:14, 8:12] = False
    assert np.allclose(loud[elsewhere], quiet[elsewhere])


def test_the_backdrop_draws_nothing_where_it_is_not_free(cooker, field_mod):
    m = field_mod
    cooker(2.0, **PULSE)
    free = np.zeros((m.VROWS, m.COLS), bool)
    free[m.BAND_TOP:m.BAND_TOP + m.BAND, :] = True
    free[12, :] = False                        # one row explicitly denied
    flat = np.zeros((m.VROWS, m.COLS), np.float32)
    v = m._backdrop(2.0, free, flat, flat, False)
    assert v[12].max() == 0.0
    assert v[~free].max() == 0.0


def test_a_hold_window_freezes_the_backdrop(cooker, field_mod):
    """Digital silence is a splice point; the field holds its breath."""
    field_mod.DEFAULTS["hold_windows"] = ((1.5, 3.0),)
    held = cooker(2.0, kick=1.0, snare=1.0, **PULSE)
    field_mod.DEFAULTS["hold_windows"] = ()
    assert held["stats"]["held"] is True


# -------------------------------------------------- the vectorisation identity

def test_hsv_is_linear_in_its_value(field_mod):
    """The emit scales one colour by a whole grid of values instead of calling
    `_hsv` per cell. That is only correct because every component of `_hsv` is
    its value times a factor of hue and saturation alone."""
    m = field_mod
    for h in (0.0, 0.2, 0.58, 0.9):
        for sat in (0.0, 0.35, 1.0):
            unit = np.array(m._hsv(h, sat, 1.0))
            for v in (0.02, 0.1, 0.5, 1.0):
                assert np.allclose(np.array(m._hsv(h, sat, v)), unit * v)
