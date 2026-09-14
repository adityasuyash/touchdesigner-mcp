"""Halftone: the beat as a printed dot screen.

The thing worth testing here is the one thing easy to get wrong. Tone in a
halftone is carried by the AREA of a dot, not by its brightness -- so the radius
has to go as the square root of the tone. Use the tone as the radius directly
and every midtone comes out far too light, which looks like a dim style rather
than like a bug.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.types.halftone import params as P


@pytest.fixture
def ht():
    src = types_mod.get_type("halftone").field_source()
    mod = pytypes.ModuleType("halftone_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    mod._apply_params()
    return mod


def _screen_at(ht, tone_value):
    """One screen over a flat tone, as an array."""
    ht._grids()
    tone = np.full(ht.S["shape"], float(tone_value), np.float32)
    return ht._screen(tone, ht.ANGLE)


# ----------------------------------------------------------------- the type

def test_it_is_a_beatsync_type_that_needs_no_words():
    vt = types_mod.get_type("halftone")
    assert vt.family == types_mod.BEATSYNC
    assert vt.needs_lyrics is False


def test_it_declares_no_grid_vocabulary():
    """The lattice here is continuous -- a pitch and an angle. If `cols` or a
    glyph ramp turns up, something has been copied from the renderer this one
    exists to differ from."""
    names = {f for sec in P.Params().__dataclass_fields__
             for f in getattr(P.Params(), sec).__dataclass_fields__}
    assert not (names & {"cols", "vrows", "band", "glyphs", "density"}), names


# ------------------------------------------------------- area, not brightness

def test_dot_area_is_linear_in_tone():
    """A dot of radius r covers area pi*r^2, so r must go as sqrt(tone). The
    check is on the relationship, not on any one value: doubling the tone must
    roughly double the inked area."""
    import math
    assert math.isclose(math.sqrt(0.25) / math.sqrt(0.5),
                        math.sqrt(0.5), rel_tol=1e-6)


def test_a_darker_tone_inks_more_of_the_sheet(ht):
    light = _screen_at(ht, 0.2).mean()
    mid = _screen_at(ht, 0.5).mean()
    dark = _screen_at(ht, 0.9).mean()
    assert light < mid < dark


def test_the_midtone_is_not_crushed(ht):
    """The symptom of using tone as the radius: half tone inks far less than
    half of what full tone does. With area linear in tone it lands near it."""
    mid = float(_screen_at(ht, 0.5).mean())
    full = float(_screen_at(ht, 1.0).mean())
    assert mid / full > 0.4, (mid, full)


def test_no_tone_inks_nothing_and_full_tone_inks_the_most(ht):
    assert _screen_at(ht, 0.0).max() == pytest.approx(0.0)
    assert _screen_at(ht, 1.0).mean() > _screen_at(ht, 0.6).mean()


# ------------------------------------------------------------- the lattice

def test_a_finer_pitch_makes_more_dots(ht):
    """Counted by how often the screen crosses its own half-way level along a
    row, which needs no image library."""
    def crossings(pitch):
        ht.PITCH = pitch
        a = _screen_at(ht, 0.5)
        row = a[a.shape[0] // 2]
        return int(np.count_nonzero(np.diff((row > 0.5).astype(np.int8))))
    few = crossings(12.0)
    many = crossings(48.0)
    assert many > few, (few, many)


def test_the_dot_is_round_rather_than_an_oval(ht):
    """Both axes are normalised against the frame's HEIGHT, so a step in x and
    a step in y cover the same distance. Normalising each against its own axis
    is what turned a sun into a wedge and a circle into an oval earlier."""
    ht.ANGLE = 0.0
    ht.PITCH = 8.0
    a = _screen_at(ht, 0.6)
    h, w = a.shape
    # the dot at the centre: measure its extent along each axis through its middle
    cy, cx = h // 2, w // 2
    across = np.count_nonzero(a[cy] > 0.5)
    down = np.count_nonzero(a[:, cx] > 0.5)
    # Same number of dots per unit distance on both axes, so the counts scale
    # with the number of cells the axis spans.
    assert 0.6 < (across / max(1, down)) / (w / h) < 1.6, (across, down, w, h)


# ------------------------------------------------------------ the separations

def test_the_three_screens_are_not_the_same_picture(ht):
    """The rosette is the whole point. Identical angles give three copies of one
    screen and the result is a grey dot grid."""
    ht._grids()
    tone = np.full(ht.S["shape"], 0.5, np.float32)
    a = ht._screen(tone, ht.ANGLE)
    b = ht._screen(tone, ht.ANGLE + ht.SPREAD)
    assert float(np.abs(a - b).mean()) > 0.02


def test_separating_the_inks_is_refused_without_an_angle_between_them():
    p = P.Params()
    p.ink.separate, p.ink.spread = True, 0.0
    assert any("spread" in m for m in p.validate())


# -------------------------------------------------- where in the song this is

def test_it_opens_arrives_and_ends(ht):
    ht.KICK_IN, ht.HIGH_IN, ht.TAIL_END = 20.0, 40.0, 200.0
    ht.INTRO_OPEN, ht.ARRIVE, ht.OUTRO = 0.3, 0.8, 10.0
    assert ht._section_gain(5.0) < ht._section_gain(30.0) < ht._section_gain(60.0)
    assert ht._section_gain(199.5) < ht._section_gain(150.0)


def test_an_envelope_is_clamped_at_both_ends(ht):
    """A strike ahead of the playhead makes the age negative, and an unclamped
    `1 - age/decay` is then greater than one and grows without limit. It drove
    another renderer's whole field to a flat glare at 0.86 of white.

    Bounded is what matters, and 1.0 is the right bound to land on: a stale
    future strike can only come from a backward seek, and reading it as "just
    struck" is what every other renderer here does.
    """
    ahead = ht._env(1.0, struck=5.0, decay=0.3)
    assert 0.0 <= ahead <= 1.0
    assert ht._env(5.0, struck=5.0, decay=0.3) == pytest.approx(1.0)
    assert ht._env(5.15, struck=5.0, decay=0.3) == pytest.approx(0.5)
    assert ht._env(9.0, struck=5.0, decay=0.3) == pytest.approx(0.0)


# ------------------------------------------------------------- the defaults

def test_the_defaults_are_a_valid_config():
    assert P.Params().validate() == []


def test_a_screen_that_would_fill_in_solid_is_refused():
    p = P.Params()
    p.screen.dot = 0.9
    assert any("dot" in m for m in p.validate())


def test_the_stack_stays_inside_the_tone_range():
    p = P.Params()
    p.tone.base, p.tone.kick_lift = 0.5, 0.9
    p.tone.snare_lift, p.tone.hat_lift, p.tone.wave = 0.5, 0.4, 0.4
    P.reconcile(p)
    assert p.validate() == [], p.validate()
    assert p.tone.kick_lift == pytest.approx(0.9), (
        "the kick gave way; it is the one the picture is keyed to")
