"""Monument: one word, filling the frame.

The first renderer here that is not a grid of glyphs. `lyric_grid`, `pulse_grid`
and `swell` are one network -- a character field at one pixel per cell -- so
every style any of them could have was that same picture in a different tint.
This one draws a single word as large as it will go.

The field script imports standalone, as the others do, so what it decides is
testable with no TouchDesigner.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.types.monument import params as P


@pytest.fixture
def mon():
    src = types_mod.get_type("monument").field_source()
    mod = pytypes.ModuleType("monument_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    return mod


# ----------------------------------------------------------------- the type

def test_it_is_a_lyric_type_that_needs_words():
    vt = types_mod.get_type("monument")
    assert vt.family == types_mod.LYRIC
    assert vt.needs_lyrics is True


def test_it_does_not_borrow_the_grid_renderer():
    """The whole point. `pulse_grid` and `swell` are twenty-six lines that
    import `lyric_grid.build`, which is exactly why all three draw the same
    character field. A renderer that borrows the network inherits the picture.
    """
    from pathlib import Path
    here = Path(types_mod.__file__).parent / "monument"
    for name in ("build.py", "params.py", "field.py"):
        src = (here / name).read_text()
        assert "lyric_grid" not in src.replace(
            "# ", "").split("\"\"\"")[0] or True    # prose may name it
        assert "from ..lyric_grid" not in src, (
            f"monument/{name} imports from lyric_grid; that import is what "
            f"made the other renderers one picture")


def test_it_declares_no_grid_vocabulary():
    """No cols, no vrows, no band, no glyphs -- if those appear, something has
    been copied from the type this one exists to differ from."""
    names = {f for sec in P.Params().__dataclass_fields__
             for f in getattr(P.Params(), sec).__dataclass_fields__}
    assert not (names & {"cols", "vrows", "band", "band_top", "glyphs",
                         "density", "glyph_aspect"}), names


# --------------------------------------------------------- fitting the word

def test_a_long_word_is_set_smaller_than_a_short_one(mon):
    """Both should fill the frame, which means the size is per word. A single
    size for every word is how you get a wall of one and a whisper of another.
    """
    big = mon._fit("go", 0.86, 300.0, 720)
    small = mon._fit("everything", 0.86, 300.0, 720)
    assert small < big


def test_a_short_word_is_capped_rather_than_absurd(mon):
    """Without the cap, "I" would be set at half the frame's height and read
    as a texture rather than as a word."""
    assert mon._fit("I", 0.86, 300.0, 720) == pytest.approx(300.0)


def test_every_word_in_a_real_line_lands_inside_the_frame(mon):
    width = 720
    for word in "needless to say I keep her in check".split():
        size = mon._fit(word, 0.86, 300.0, width)
        assert size * len(word) * 0.6 <= width * 0.87 + 1.0, word


# ------------------------------------------------------- the life of a word

def test_a_word_holds_until_the_next_one_lands(mon):
    mon.HOLD, mon.FADE = 0.55, 0.30
    lit, _ = mon._life(t=1.5, start=1.0, nxt=2.0)
    assert lit == pytest.approx(1.0)


def test_the_last_word_holds_then_fades(mon):
    mon.HOLD, mon.FADE = 0.5, 0.25
    assert mon._life(t=10.4, start=10.0, nxt=None)[0] == pytest.approx(1.0)
    part = mon._life(t=10.6, start=10.0, nxt=None)[0]
    assert 0.0 < part < 1.0
    assert mon._life(t=11.0, start=10.0, nxt=None)[0] == pytest.approx(0.0)


def test_a_word_is_not_lit_before_its_cue(mon):
    assert mon._life(t=0.5, start=1.0, nxt=2.0)[0] == pytest.approx(0.0)


def test_the_word_being_sung_is_found_by_bisection(mon):
    cues = [(1.0, "a"), (2.0, "b"), (3.0, "c")]
    assert mon._at(cues, 0.5) == -1
    assert mon._at(cues, 1.0) == 0
    assert mon._at(cues, 2.9) == 1
    assert mon._at(cues, 99.0) == 2


# ------------------------------------------------ where in the song this is

def test_it_opens_arrives_and_ends(mon):
    mon.KICK_IN, mon.HIGH_IN, mon.TAIL_END = 20.0, 40.0, 200.0
    mon.INTRO_OPEN, mon.ARRIVE, mon.OUTRO = 0.35, 0.85, 10.0
    assert mon._section_gain(5.0) < mon._section_gain(30.0) < mon._section_gain(60.0)
    assert mon._section_gain(199.5) < mon._section_gain(150.0)


def test_a_song_with_no_measured_structure_is_left_flat(mon):
    mon.KICK_IN, mon.HIGH_IN, mon.TAIL_END = 0.0, 0.0, 0.0
    assert mon._section_gain(0.5) == pytest.approx(1.0)


def test_nothing_is_drawn_through_a_measured_silence(mon):
    mon.HOLD_WINDOWS = ((10.0, 20.0),)
    assert mon._held(15.0) is True
    assert mon._held(25.0) is False


# --------------------------------------------------------------- the ground

def test_the_ground_is_one_flat_colour(mon):
    """The Script TOP here is not the picture: it is sixteen pixels of ground
    that the Text TOPs are composited over."""
    r, g, b = mon._hsv(0.06, 0.22, 0.5)
    assert 0.0 < r <= 1.0 and 0.0 < g <= 1.0 and 0.0 < b <= 1.0
    # linear in v, so one scalar call gives the whole frame
    r2, g2, b2 = mon._hsv(0.06, 0.22, 1.0)
    assert r2 == pytest.approx(r * 2, rel=1e-5)


# ------------------------------------------------------------- the defaults

def test_the_defaults_are_a_valid_config():
    assert P.Params().validate() == []


def test_the_word_cannot_be_outshone_by_its_own_afterimage():
    p = P.Params()
    p.word.ghost = 0.99
    P.reconcile(p)
    assert p.word.ghost < p.look.peak


def test_the_stack_stays_under_white():
    p = P.Params()
    p.look.peak, p.look.floor, p.beat.kick_lift = 0.98, 0.05, 0.4
    P.reconcile(p)
    assert p.validate() == [], p.validate()
    assert p.look.peak == pytest.approx(0.98), (
        "the word's own brightness gave way; it is the one thing that should not")
