"""Approach: the words travel toward you.

From the Chainsmokers' "Closer", where the lyrics fly through 3D space. The
things worth testing are the two that would be invisible if wrong: whether the
projection actually behaves like perspective, and whether a word ends up in the
slab whose font size matches its depth. Get the second one wrong and words are
drawn at the wrong size for where they are, which reads as "the type is jumpy"
rather than as an arithmetic mistake.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.config import Config
from lyricfield.types.approach import params as P
from lyricfield.types.approach.build import network


@pytest.fixture
def ap():
    src = types_mod.get_type("approach").field_source()
    mod = pytypes.ModuleType("approach_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    mod._apply_params()
    return mod


# ----------------------------------------------------------------- the type

def test_it_is_a_lyric_type_that_needs_words():
    vt = types_mod.get_type("approach")
    assert vt.family == types_mod.LYRIC
    assert vt.needs_lyrics is True


def test_it_does_not_borrow_another_renderer():
    from pathlib import Path
    here = Path(types_mod.__file__).parent / "approach"
    for name in ("build.py", "params.py", "field.py"):
        src = (here / name).read_text()
        for other in ("lyric_grid", "orbit", "swarm", "monument"):
            assert f"from ..{other}" not in src, f"approach/{name} imports {other}"


def test_it_declares_no_grid_vocabulary():
    names = {f for sec in P.Params().__dataclass_fields__
             for f in getattr(P.Params(), sec).__dataclass_fields__}
    assert not (names & {"cols", "vrows", "band", "glyphs", "density"}), names


# ------------------------------------------------------------- perspective

def test_a_word_gets_bigger_as_it_comes(ap):
    """The whole point. Apparent size goes as 1/z, so the slab index has to
    fall as the word approaches."""
    ap.SECONDS = 2.0
    early = ap._depth_at(0.2, 0.0)
    late = ap._depth_at(1.8, 0.0)
    assert early > late
    assert ap._slab_for(early) > ap._slab_for(late)


def test_depth_falls_at_a_constant_rate(ap):
    """Constant velocity in depth. The apparent motion is then hyperbolic --
    a long drift and a rush at the end -- which is what the reference does."""
    ap.SECONDS, ap.FAR_Z, ap.NEAR_Z = 2.0, 7.0, 1.0
    a = ap._depth_at(0.5, 0.0) - ap._depth_at(0.0, 0.0)
    b = ap._depth_at(1.5, 0.0) - ap._depth_at(1.0, 0.0)
    assert a == pytest.approx(b)


def test_a_word_starts_at_the_far_plane_and_ends_at_the_near_one(ap):
    ap.SECONDS, ap.FAR_Z, ap.NEAR_Z = 2.0, 7.0, 0.5
    assert ap._depth_at(0.0, 0.0) == pytest.approx(7.0)
    assert ap._depth_at(2.0, 0.0) == pytest.approx(0.5)


def test_an_offset_shrinks_with_distance(ap):
    """A word three units off-axis at depth 1 must be one unit off at depth 3,
    or it is not perspective, it is a slide."""
    ap.SPREAD = 1.0
    cues = [(0.0, "one")]
    ap.SECONDS, ap.FAR_Z, ap.NEAR_Z = 10.0, 9.0, 0.5
    ap.VANISH_X = ap.VANISH_Y = 0.5
    far = ap._live(cues, 0.1)
    near = ap._live(cues, 9.0)
    assert far and near
    cx = ap.WIDTH * 0.5
    assert abs(far[0][1] - cx) < abs(near[0][1] - cx)


def test_every_word_keeps_its_own_lane(ap):
    """The offset has to be a function of the word's index, not of the frame.
    A per-frame random would make a word jitter across the screen, and would
    also mean the piece did not render the same way twice."""
    assert ap._offset_for(3) == ap._offset_for(3)
    assert ap._offset_for(3) != ap._offset_for(4)


def test_offsets_stay_inside_the_spread(ap):
    ap.SPREAD = 0.4
    for i in range(50):
        dx, dy = ap._offset_for(i)
        assert abs(dx) <= 0.4 + 1e-9 and abs(dy) <= 0.4 + 1e-9


# ------------------------------------------------------------- the slabs

def test_the_field_and_the_builder_agree_about_the_slabs(ap):
    """They must. `build` sets each slab's font size from these depths and the
    field decides which slab a word goes in from them; disagreeing would draw
    words at a size that does not match their depth, silently."""
    p = P.Params()
    ap.NEAR_Z, ap.FAR_Z, ap.LAYERS = (p.travel.near_z, p.travel.far_z,
                                      p.depth.layers)
    ap.S.pop("slabs", None)
    assert ap._slabs() == pytest.approx(P.slab_depths(p))


def test_the_slabs_are_spaced_geometrically():
    """Linear spacing would put the near slabs on top of each other in apparent
    size and leave a jump at the far end."""
    z = P.slab_depths(P.Params())
    ratios = [z[i + 1] / z[i] for i in range(len(z) - 1)]
    assert max(ratios) - min(ratios) < 1e-6


def test_the_nearest_slab_is_nearest(ap):
    z = ap._slabs()
    assert z == sorted(z)
    assert ap._slab_for(z[0]) == 0
    assert ap._slab_for(z[-1]) == len(z) - 1


def test_a_word_outside_the_travel_is_not_drawn(ap):
    ap.SECONDS, ap.FAR_Z, ap.NEAR_Z = 2.0, 7.0, 0.5
    cues = [(5.0, "soon")]
    assert ap._live(cues, 4.0) == []        # before its cue
    assert ap._live(cues, 8.0) == []        # already past the camera


# ----------------------------------------------------- the specification DAT

def test_each_slab_gets_its_own_table_with_a_header(ap):
    live = [(0, 10, 20, "near"), (2, 30, 40, "far")]
    bodies = ap._specs(live, 4)
    assert len(bodies) == 4
    for b in bodies:
        assert b.split("\n")[0] == "x\ty\ttext"
    assert "near" in bodies[0] and "far" in bodies[2]
    assert bodies[1] == "x\ty\ttext"        # empty slab draws nothing


def test_the_table_is_written_from_the_lower_left(ap):
    """The Specification DAT's origin is lower-left. Writing top-down puts every
    word upside down in the frame, which reads as a broken renderer rather than
    as an axis mistake."""
    ap.VANISH_Y = 0.0                        # top of the frame
    ap.SPREAD = 0.0
    ap.SECONDS, ap.FAR_Z, ap.NEAR_Z = 2.0, 7.0, 0.5
    live = ap._live([(0.0, "up")], 1.0)
    assert live
    assert live[0][2] > ap.HEIGHT * 0.5, (
        "a word at the top of the frame should have a HIGH y in lower-left "
        "pixel coordinates")


# -------------------------------------------------- where in the song this is

def test_it_opens_arrives_and_ends(ap):
    ap.KICK_IN, ap.HIGH_IN, ap.TAIL_END = 20.0, 40.0, 200.0
    ap.INTRO_OPEN, ap.ARRIVE, ap.OUTRO = 0.3, 0.85, 10.0
    assert ap._section_gain(5.0) < ap._section_gain(30.0) < ap._section_gain(60.0)
    assert ap._section_gain(199.5) < ap._section_gain(150.0)


def test_nothing_is_drawn_through_a_measured_silence(ap):
    ap.HOLD_WINDOWS = ((10.0, 20.0),)
    assert ap._held(15.0) is True
    assert ap._held(25.0) is False


# ---------------------------------------------------------------- the network

def test_the_slabs_are_composited_near_over_far():
    """The only ordering in the whole renderer that has to be right for the
    depth to read: a near word covers a far one, never the other way round."""
    specs = network(Config(type="approach"))
    by_name = {s.name: s for s in specs}
    overs = [s for s in specs if s.name.startswith("ap_over")]
    assert overs
    for s in overs:
        near, far = s.inputs
        assert near.startswith("ap_lvl"), s.name
        # input1 goes over input2 in a composite, and the near slab is input1
        assert near in by_name and far in by_name


def test_there_is_one_text_top_and_one_table_per_slab():
    cfg = Config(type="approach")
    n = cfg.params.depth.layers
    specs = network(cfg)
    for i in range(n):
        assert any(s.name == f"ap_text{i}" and s.type == "textTOP" for s in specs)
        assert any(s.name == f"spec{i}" and s.type == "tableDAT" for s in specs)


def test_the_slab_font_sizes_follow_the_depths():
    cfg = Config(type="approach")
    specs = {s.name: s for s in network(cfg)}
    depths = P.slab_depths(cfg.params)
    one = cfg.params.travel.size_at_one
    for i, z in enumerate(depths):
        assert specs[f"ap_text{i}"].params["fontsizex"] == pytest.approx(
            round(one / z, 2))


def test_the_font_size_is_in_pixels_rather_than_points():
    """Points is the default and follows the display's DPI, which once made a
    grid's row pitch depend on the monitor it was built on."""
    specs = {s.name: s for s in network(Config(type="approach"))}
    p = specs["ap_text0"].params
    assert p["fontsizexunit"] == "pixels" and p["fontsizeyunit"] == "pixels"


def test_the_inline_text_is_cleared():
    """A Text TOP draws its own inline `text` and ignores its DAT while that is
    non-empty. It ships holding the word "derivative"."""
    specs = {s.name: s for s in network(Config(type="approach"))}
    assert specs["ap_text0"].params["text"] == ""


# ------------------------------------------------------------- the defaults

def test_the_defaults_are_a_valid_config():
    assert P.Params().validate() == []


def test_a_far_plane_behind_the_near_one_is_refused():
    p = P.Params()
    p.travel.far_z = 0.2
    assert any("far_z" in m for m in p.validate())


def test_the_stack_stays_under_white():
    p = P.Params()
    p.look.peak, p.look.floor, p.beat.kick_lift = 0.98, 0.05, 0.4
    P.reconcile(p)
    assert p.validate() == [], p.validate()
    assert p.look.peak == pytest.approx(0.98), (
        "the type's own brightness gave way; it is the one thing that should not")
