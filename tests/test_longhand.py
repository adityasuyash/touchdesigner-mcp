"""Longhand: handwritten lyrics in a volume, and a camera drifting through it.

From the Chainsmokers' "Closer" lyric video, which the sources describe as
"live action footage compiled with lyrics that fly through 3d space". The
reference has been read wrong twice: `approach` flew words at the camera down a
tunnel, and the first `longhand` panned along a flat written line. Neither had
both halves. The words hold still, scattered through a space, and the eye moves
among them.

The properties worth pinning are the ones that separate that from a slideshow
and from a flat layer that has been scaled, because the failure mode is not an
error: it is a renderer that works and feels wrong.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.config import Config
from lyricfield.types.longhand import params as P
from lyricfield.types.longhand.build import network

CUES = [(1.0, "every"), (1.5, "word"), (2.2, "finds"), (2.6, "its"),
        (3.4, "place"), (4.0, "then"), (4.9, "it"), (5.3, "fades")]


@pytest.fixture
def lh():
    src = types_mod.get_type("longhand").field_source()
    mod = pytypes.ModuleType("longhand_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    mod._apply_params()
    mod.S.clear()
    return mod


# ----------------------------------------------------------------- the type

def test_it_is_a_lyric_type_that_needs_words():
    vt = types_mod.get_type("longhand")
    assert vt.family == types_mod.LYRIC
    assert vt.needs_lyrics is True


def test_it_is_written_by_hand():
    """The script face is most of the look; a grotesque would read as a
    caption crawl rather than as somebody's handwriting."""
    font = P.Params().stage.font
    assert font in ("Bradley Hand", "Snell Roundhand", "Brush Script MT",
                    "Chalkboard", "Marker Felt"), font


def test_it_does_not_borrow_another_renderer():
    from pathlib import Path
    here = Path(types_mod.__file__).parent / "longhand"
    for name in ("build.py", "params.py", "field.py"):
        src = (here / name).read_text()
        for other in ("lyric_grid", "orbit", "swarm", "monument", "window"):
            assert f"from ..{other}" not in src, f"longhand/{name} imports {other}"


# ------------------------------------------------------------- the volume

def test_the_volume_is_laid_out_once_and_does_not_move(lh):
    """The camera moves; the writing does not. Re-placing the words each frame
    would make them swim against each other."""
    a = lh._layout(CUES)
    b = lh._layout(CUES)
    assert a is b, "the layout was rebuilt"


def test_the_lyrics_run_away_from_the_camera_rather_than_round_it(lh):
    """`march`: each word is further off than the one before, so the song has a
    direction. Without it the words sit in one room and the camera orbits."""
    laid = lh._layout(CUES)
    zs = [z for _x, _y, z in laid]
    assert zs == sorted(zs)
    assert len(set(zs)) == len(zs), "two words share a depth"


def test_the_words_are_scattered_off_the_camera_axis(lh):
    """Otherwise every word is dead centre and the volume is a corridor."""
    lh.S.pop("laid", None)
    laid = lh._layout(CUES * 4)
    xs = [x for x, _y, _z in laid]
    ys = [y for _x, y, _z in laid]
    assert max(xs) - min(xs) > 0.5, "the words sit on the axis in x"
    assert max(ys) - min(ys) > 0.3, "the words sit on the axis in y"


def test_the_scatter_does_not_repeat_word_to_word(lh):
    """Two incommensurable periods per axis. One would make a regular wave, and
    the camera would visibly retrace the same path every few words."""
    lh.S.pop("laid", None)
    laid = lh._layout([(i * 0.4, "word") for i in range(40)])
    xs = np.array([x for x, _y, _z in laid])
    first, second = xs[:20], xs[20:]
    assert float(np.abs(first - second).mean()) > 0.2


def test_a_word_is_placed_from_its_index_alone(lh):
    """No RNG anywhere, so a re-render is identical and two machines agree --
    the rule CLAUDE.md sets for anything with a choice."""
    lh.S.pop("laid", None)
    once = lh._layout(CUES)
    lh.S.pop("laid", None)
    twice = lh._layout([(t, w.upper()) for t, w in CUES])
    assert once == twice, "the layout depends on something other than the index"


# ------------------------------------------------------------- the camera

def test_the_camera_follows_the_word_being_sung(lh):
    lh.S.pop("laid", None)
    laid = lh._layout(CUES)
    early = lh._camera(CUES, laid, 1.1)
    late = lh._camera(CUES, laid, 5.2)
    assert late[2] > early[2], "the camera did not travel into the volume"


def test_the_camera_keeps_the_sung_word_in_front_of_it(lh):
    """`standoff`. At zero the eye arrives inside the word it is looking at and
    the one frame the renderer exists to draw is clipped by the near wall."""
    lh.S.pop("laid", None)
    lh.FLOAT_ = 0.0
    laid = lh._layout(CUES)
    for i, (t, _w) in enumerate(CUES):
        cam = lh._camera(CUES, laid, t + 1e-4)
        ahead = laid[i][2] - cam[2]
        assert ahead >= lh.NEAR_Z, (
            f"word {i} is {ahead:.2f} ahead of the camera, inside near_z "
            f"{lh.NEAR_Z}")


def test_something_has_already_gone_past_the_camera(lh):
    """The difference between travelling through a space and queueing at one.

    With `standoff` shorter than `march` past the near wall, every frame holds
    only words yet to come: measured at 0.85 against a march of 0.62, not one
    word was ever behind the eye.
    """
    lh.S.pop("laid", None)
    lh.FLOAT_ = 0.0
    laid = lh._layout(CUES)
    i = 4
    cam = lh._camera(CUES, laid, CUES[i][0] + 1e-4)
    behind = [j for j in range(len(CUES)) if laid[j][2] - cam[2] < lh.NEAR_Z]
    assert behind, "nothing has passed the camera; the words are a queue"


def test_the_camera_is_still_moving_when_the_next_word_lands(lh):
    """The whole feel. `chase` above 1 means it has not arrived by the time the
    next cue fires, so it never stops -- a camera that arrives and waits is a
    slideshow with a pan on it."""
    lh.S.pop("laid", None)
    lh.FLOAT_ = 0.0                      # isolate the chase from the drift
    laid = lh._layout(CUES)
    # Where it is exactly as the second word is sung, against where that word is.
    at_cue = lh._camera(CUES, laid, CUES[1][0] - 1e-4)
    start, target = laid[0][2], laid[1][2]
    travelled = (at_cue[2] + lh.STANDOFF - start) / (target - start)
    assert 0.5 < travelled < 0.995, (
        f"the camera was {travelled:.0%} of the way when the next word landed; "
        f"at 100% it stops between words")


def test_a_chase_that_arrives_early_is_refused():
    p = P.Params()
    p.camera.chase = 0.8
    assert any("slideshow" in m for m in p.validate())
    P.reconcile(p)
    assert p.validate() == []


def test_the_camera_never_stops_even_on_a_held_word(lh):
    """The drift. Without it a long-held word freezes the frame, and the next
    word then reads as a jump cut."""
    lh.S.pop("laid", None)
    laid = lh._layout(CUES)
    seen = {lh._camera(CUES, laid, 5.3 + i * 0.05) for i in range(40)}
    assert len(seen) > 30, "the camera sat still"


def test_the_camera_is_a_pure_function_of_its_timestamp(lh):
    """No per-frame integration, so a dropped frame or a seek cannot change
    what is drawn and the song renders the same way twice."""
    lh.S.pop("laid", None)
    laid = lh._layout(CUES)
    assert lh._camera(CUES, laid, 3.17) == lh._camera(CUES, laid, 3.17)


# ------------------------------------------------- what reaches the screen

def test_the_words_around_the_sung_one_are_drawn(lh):
    lh.S.pop("laid", None)
    laid = lh._layout(CUES)
    cam = lh._camera(CUES, laid, 3.5)
    bodies, drawn = lh._spec(CUES, laid, 3.5, cam, 1.0)
    assert drawn > 1, "only one word reached the screen; the volume should fill"
    assert len(bodies) == len(lh.SLABS), "one Spec DAT per slab"
    for b in bodies:
        assert b.split("\n")[0] == "x\ty\ttext"


def test_the_words_are_spread_across_more_than_one_slab(lh):
    """If everything lands on one slab the frame is a flat layer and the depth
    is decorative."""
    lh.S.pop("laid", None)
    laid = lh._layout(CUES)
    cam = lh._camera(CUES, laid, 3.5)
    bodies, _ = lh._spec(CUES, laid, 3.5, cam, 1.0)
    used = [i for i, b in enumerate(bodies) if len(b.split("\n")) > 1]
    assert len(used) > 1, f"every visible word is on slab {used}"


def test_a_nearer_word_is_drawn_larger(lh):
    """The perspective itself, asked of the two halves together: the slab a
    word is assigned to must be the one whose font size matches its distance.

    `field._slab_of` picks the slab and `build` fixes the sizes, from the same
    list. If they drifted apart a word would be drawn at a size that did not
    match how far away it was, and nothing on screen would say why.
    """
    from lyricfield.types.longhand.params import Params, slab_depths

    depths = slab_depths(Params())
    assert [lh._slab_of(z) for z in depths] == list(range(len(depths)))
    # and between slabs it rounds to one of the two neighbours, not to an end
    mid = (depths[1] * depths[2]) ** 0.5
    assert lh._slab_of(mid) in (1, 2)


def test_the_volume_is_written_from_the_lower_left(lh):
    """The Specification DAT's origin, and the thing that has cost time twice
    here. Written top-down the whole frame renders upside down, which reads as
    a broken renderer rather than as an axis slip."""
    lh.S.pop("laid", None)
    lh.FOCUS_Y = 0.0                     # the focus at the TOP of the frame
    lh.SPREAD_Y = 0.0
    lh.FLOAT_ = 0.0
    laid = lh._layout(CUES)
    cam = lh._camera(CUES, laid, 3.5)
    bodies, _ = lh._spec(CUES, laid, 3.5, cam, 1.0)
    ys = [int(r.split("\t")[1]) for b in bodies for r in b.split("\n")[1:]]
    assert ys and min(ys) > lh.HEIGHT * 0.5, (
        "a word at the top of the frame should have a HIGH y in lower-left "
        "pixel coordinates")


def test_words_outside_the_walls_are_dropped_rather_than_drawn(lh):
    """Every row costs the Text TOP work, and a word behind the camera or past
    the far wall is not on screen in any sense that matters."""
    lh.S.pop("laid", None)
    lh.REACH = 40
    laid = lh._layout(CUES * 6)
    cam = lh._camera(CUES * 6, laid, 3.5)
    _bodies, drawn = lh._spec(CUES * 6, laid, 3.5, cam, 1.0)
    assert drawn < len(CUES) * 6, "nothing was dropped despite a bounded volume"


def test_the_smear_follows_the_camera_and_stops_when_it_does(lh):
    """The motion blur is the third thing every breakdown of that video names,
    and it has to be a function of the camera rather than a constant -- a fixed
    smear reads as a soft render, not as movement."""
    lh.S.pop("laid", None)
    laid = lh._layout(CUES)
    moving = lh._smear(CUES, laid, CUES[2][0] + 0.02)
    assert max(abs(v) for v in moving) > 0.0, "the smear is dead"
    # and it is a pure function of t, like everything else here
    assert lh._smear(CUES, laid, 3.17) == lh._smear(CUES, laid, 3.17)


def test_nothing_is_written_through_a_measured_silence(lh):
    lh.HOLD_WINDOWS = ((10.0, 20.0),)
    assert lh._held(15.0) is True
    assert lh._held(25.0) is False


def test_a_song_with_no_cues_does_not_raise(lh):
    lh.S.pop("laid", None)
    laid = lh._layout([])
    cam = lh._camera([], laid, 3.0)
    assert cam == (0.0, 0.0, -lh.STANDOFF)
    bodies, drawn = lh._spec([], laid, 3.0, cam, 1.0)
    assert drawn == 0 and set(bodies) == {"x\ty\ttext"}


# -------------------------------------------------- where in the song this is

def test_it_opens_arrives_and_ends(lh):
    lh.KICK_IN, lh.HIGH_IN, lh.TAIL_END = 20.0, 40.0, 200.0
    lh.INTRO_OPEN, lh.ARRIVE, lh.OUTRO = 0.35, 0.88, 10.0
    assert lh._section_gain(5.0) < lh._section_gain(30.0) < lh._section_gain(60.0)
    assert lh._section_gain(199.5) < lh._section_gain(150.0)


# ---------------------------------------------------------------- the network

def test_one_text_top_per_depth_slab():
    """A Text TOP has ONE font size for its whole Specification DAT, so
    continuous perspective is not available and the space has to be quantised.
    This is the machinery `approach` was written for and the first `longhand`
    threw away when it flattened the reference into a pan."""
    specs = network(Config(type="longhand"))
    texts = [s for s in specs if s.type == "textTOP"]
    layers = P.Params().depth.layers
    assert len(texts) == layers, [s.name for s in texts]
    assert {t.params["specdat"] for t in texts} == {
        f"spec{i}" for i in range(layers)}


def test_a_nearer_slab_is_set_to_a_larger_font():
    """The perspective, in the half `build.py` owns. Sizes come from
    `slab_depths`, the same list the field script assigns words from."""
    specs = {s.name: s for s in network(Config(type="longhand"))}
    sizes = [specs[f"lh_text{i}"].params["fontsizex"]
             for i in range(P.Params().depth.layers)]
    assert sizes == sorted(sizes, reverse=True), sizes
    depths = P.slab_depths(P.Params())
    at_one = P.Params().stage.size_at_one
    for px, z in zip(sizes, depths):
        assert px == pytest.approx(at_one / z, rel=1e-3), (
            "a slab's font size does not match the depth it stands at")


def test_the_slabs_are_stacked_farthest_first():
    """So a near word covers a far one rather than the other way round. This is
    the only thing in the build that has to be right for the depth to read at
    all, and getting it backwards looks like a sorting bug in the layout."""
    specs = {s.name: s for s in network(Config(type="longhand"))}
    n = P.Params().depth.layers
    # Each composite takes the nearer slab first and everything farther second.
    for i in range(n - 2, -1, -1):
        over = specs[f"lh_over{i}"]
        assert over.params["operand"] == "over"
        assert over.inputs[0] == f"lh_lvl{i}", over.inputs
    # and the farthest slab is where the stack begins
    assert f"lh_over{n - 1}" not in specs


def test_distance_costs_light_as_well_as_size():
    """Fog. Size alone reads as a flat layer that has been scaled."""
    specs = {s.name: s for s in network(Config(type="longhand"))}
    lvls = [specs[f"lh_lvl{i}"].params["brightness1"]
            for i in range(P.Params().depth.layers)]
    assert lvls == sorted(lvls, reverse=True), lvls
    assert lvls[-1] < lvls[0] * 0.5, "the far slab is barely dimmer"


def test_the_farthest_slab_is_the_one_out_of_focus():
    """Haze. Blurring every slab equally is a soft render; blurring the near
    one is a broken one."""
    specs = {s.name: s for s in network(Config(type="longhand"))}
    n = P.Params().depth.layers
    assert specs["lh_haze"].inputs == [f"lh_text{n - 1}"]
    assert specs[f"lh_lvl{n - 1}"].inputs == ["lh_haze"]


def test_the_smear_averages_its_taps_rather_than_stacking_them():
    """Three taps added and then scaled back by a third, so a still frame is
    exactly as bright as it was before the branch existed. Brightness stacking
    is a defect this project has fixed three times."""
    specs = {s.name: s for s in network(Config(type="longhand"))}
    assert specs["lh_smear"].params["brightness1"] == pytest.approx(1 / 3, abs=1e-3)
    assert specs["lh_mix2"].inputs == ["lh_mix1", "lh_tap_b"]
    assert specs["lh_sum1"].inputs[0] == "lh_smear"


def test_the_smear_branch_is_absent_when_it_is_switched_off():
    cfg = Config(type="longhand")
    cfg.blur.amount = 0.0
    names = {s.name for s in network(cfg)}
    assert not {n for n in names if n.startswith("lh_tap")}
    assert "lh_smear" not in names


def test_the_inline_text_is_cleared():
    """A Text TOP draws its own inline `text` and ignores its DAT while that is
    non-empty. It ships holding the word "derivative"."""
    specs = {s.name: s for s in network(Config(type="longhand"))}
    for i in range(P.Params().depth.layers):
        assert specs[f"lh_text{i}"].params["text"] == ""


def test_the_font_size_is_in_pixels_rather_than_points():
    specs = {s.name: s for s in network(Config(type="longhand"))}
    for i in range(P.Params().depth.layers):
        p = specs[f"lh_text{i}"].params
        assert p["fontsizexunit"] == "pixels" and p["fontsizeyunit"] == "pixels"


def test_nothing_may_exceed_white():
    specs = {s.name: s for s in network(Config(type="longhand"))}
    assert specs["lh_clamp"].params["operand"] == "minimum"
    assert specs["out"].inputs == ["lh_clamp"]


# ------------------------------------------------------------- the defaults

def test_the_defaults_are_a_valid_config():
    assert P.Params().validate() == []


def test_the_stack_stays_under_white():
    p = P.Params()
    p.look.peak, p.look.floor, p.beat.kick_lift = 0.98, 0.1, 0.3
    P.reconcile(p)
    assert p.validate() == [], p.validate()
    assert p.look.peak == pytest.approx(0.98), (
        "the writing's own brightness gave way; it is legibility, not taste")


def test_no_two_sections_share_a_key():
    import collections
    p = P.Params()
    names = [f for sec in p.__dataclass_fields__
             for f in getattr(p, sec).__dataclass_fields__]
    dupes = [k for k, n in collections.Counter(names).items() if n > 1]
    assert not dupes, dupes
