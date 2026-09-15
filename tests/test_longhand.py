"""Longhand: a camera travelling a written line.

From the Chainsmokers' "Closer" lyric video, read correctly the second time.
The first attempt -- `approach` -- flew words at the camera through depth
slabs; the video pans along one long handwritten string of the lyrics, word to
word. Two different renderers from the same reference, and the difference
between them is the whole reason this file exists.

The properties worth pinning are the ones that separate a camera pan from a
slideshow, because the failure mode is not an error: it is a renderer that
works and feels wrong.
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


# --------------------------------------------------------------- the line

def test_the_line_is_laid_out_once_and_does_not_move(lh):
    """The camera moves; the writing does not. Re-laying it each frame would
    make the words swim against each other."""
    a = lh._layout(CUES)
    b = lh._layout(CUES)
    assert a is b, "the layout was rebuilt"


def test_words_run_along_the_line_in_order(lh):
    laid = lh._layout(CUES)
    alongs = [a for a, _ in laid]
    assert alongs == sorted(alongs)
    assert len(set(alongs)) == len(alongs), "two words share a position"


def test_a_long_word_takes_more_of_the_line_than_a_short_one(lh):
    laid = lh._layout([(0.0, "a"), (1.0, "extraordinary"), (2.0, "b")])
    assert (laid[2][0] - laid[1][0]) > (laid[1][0] - laid[0][0])


def test_the_line_wanders_rather_than_running_ruled(lh):
    laid = lh._layout(CUES * 4)
    drops = [d for _, d in laid]
    assert max(drops) - min(drops) > 1.0, "the line is level; it should wander"


def test_the_wander_does_not_repeat_word_to_word(lh):
    """Two long incommensurable periods. One would make a regular wave, which
    reads as a ribbon rather than as handwriting."""
    lh.S.pop("laid", None)
    laid = lh._layout([(i * 0.4, "word") for i in range(40)])
    drops = np.array([d for _, d in laid])
    first, second = drops[:20], drops[20:]
    assert float(np.abs(first - second).mean()) > 0.5


# ------------------------------------------------------------- the camera

def test_the_camera_follows_the_word_being_sung(lh):
    lh.S.pop("laid", None)
    laid = lh._layout(CUES)
    early, _ = lh._camera(CUES, laid, 1.1)
    late, _ = lh._camera(CUES, laid, 5.2)
    assert late > early


def test_the_camera_is_still_moving_when_the_next_word_lands(lh):
    """The whole feel. `chase` above 1 means it has not arrived by the time the
    next cue fires, so it never stops -- a camera that arrives and waits is a
    slideshow with a pan on it."""
    lh.S.pop("laid", None)
    lh.FLOAT_ = 0.0                      # isolate the chase from the drift
    laid = lh._layout(CUES)
    # Where it is exactly as the second word is sung, against where that word is.
    at_cue, _ = lh._camera(CUES, laid, CUES[1][0] - 1e-4)
    target = laid[1][0]
    start = laid[0][0]
    travelled = (at_cue - start) / (target - start)
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
    along, drop = lh._camera(CUES, laid, 3.5)
    body, drawn = lh._spec(CUES, laid, 3.5, along, drop, 1.0)
    assert drawn > 1, "only one word reached the screen; the line should trail"
    assert body.split("\n")[0] == "x\ty\ttext"


def test_the_line_is_written_from_the_lower_left(lh):
    """The Specification DAT's origin, and the thing that has cost time twice
    here. Written top-down the whole line renders upside down, which reads as a
    broken renderer rather than as an axis slip."""
    lh.S.pop("laid", None)
    lh.FOCUS_Y = 0.0                     # the focus at the TOP of the frame
    lh.MEANDER = 0.0
    lh.FLOAT_ = 0.0
    laid = lh._layout(CUES)
    along, drop = lh._camera(CUES, laid, 3.5)
    body, _ = lh._spec(CUES, laid, 3.5, along, drop, 1.0)
    ys = [int(r.split("\t")[1]) for r in body.split("\n")[1:]]
    assert ys and min(ys) > lh.HEIGHT * 0.5, (
        "a word at the top of the frame should have a HIGH y in lower-left "
        "pixel coordinates")


def test_far_words_are_dropped_rather_than_drawn_invisibly(lh):
    """Every row costs the Text TOP work, and a word dimmed past the floor is
    not on screen in any sense that matters."""
    lh.S.pop("laid", None)
    lh.REACH = 40
    lh.FALLOFF = 0.9
    laid = lh._layout(CUES)
    along, drop = lh._camera(CUES, laid, 3.5)
    _body, drawn = lh._spec(CUES, laid, 3.5, along, drop, 1.0)
    assert drawn < len(CUES), "nothing was dropped despite a hard falloff"


def test_nothing_is_written_through_a_measured_silence(lh):
    lh.HOLD_WINDOWS = ((10.0, 20.0),)
    assert lh._held(15.0) is True
    assert lh._held(25.0) is False


def test_a_song_with_no_cues_does_not_raise(lh):
    lh.S.pop("laid", None)
    laid = lh._layout([])
    assert lh._camera([], laid, 3.0) == (0.0, 0.0)
    body, drawn = lh._spec([], laid, 3.0, 0.0, 0.0, 1.0)
    assert drawn == 0 and body == "x\ty\ttext"


# -------------------------------------------------- where in the song this is

def test_it_opens_arrives_and_ends(lh):
    lh.KICK_IN, lh.HIGH_IN, lh.TAIL_END = 20.0, 40.0, 200.0
    lh.INTRO_OPEN, lh.ARRIVE, lh.OUTRO = 0.35, 0.88, 10.0
    assert lh._section_gain(5.0) < lh._section_gain(30.0) < lh._section_gain(60.0)
    assert lh._section_gain(199.5) < lh._section_gain(150.0)


# ---------------------------------------------------------------- the network

def test_one_text_top_rather_than_depth_slabs():
    """The correction this renderer exists for. `approach` needed one Text TOP
    per depth because a Text TOP has a single font size; here every word is the
    same size, because the camera travels ALONG the line rather than toward
    it."""
    specs = network(Config(type="longhand"))
    texts = [s for s in specs if s.type == "textTOP"]
    assert len(texts) == 1, [s.name for s in texts]
    assert texts[0].params["specdat"] == "spec"


def test_the_inline_text_is_cleared():
    """A Text TOP draws its own inline `text` and ignores its DAT while that is
    non-empty. It ships holding the word "derivative"."""
    specs = {s.name: s for s in network(Config(type="longhand"))}
    assert specs["lh_text"].params["text"] == ""


def test_the_font_size_is_in_pixels_rather_than_points():
    specs = {s.name: s for s in network(Config(type="longhand"))}
    p = specs["lh_text"].params
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
