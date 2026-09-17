"""Longhand: lyrics lettered by hand over footage.

From frames of the Chainsmokers' "Closer" lyric video. It was read wrong three
times from text first -- words flying at the camera, a pan along one written
line, words scattered through a volume -- so the properties pinned here are the
ones a fourth misreading would break: flat, phrase at a time, and irregular in
a way a font is not.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.config import Config
from lyricfield.types.longhand import params as P
from lyricfield.types.longhand import build as B
from lyricfield.types.longhand.build import network

CUES = [(1.0, "every", 1), (1.5, "word", 1), (2.2, "finds", 1), (2.6, "its", 1),
        (3.4, "place", 1), (4.0, "then", 2), (4.9, "it", 2), (5.3, "fades", 2)]


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


def test_it_is_lettered_by_hand():
    """A hand face is most of the look; a grotesque reads as a caption. The
    reference's is cursive with connected strokes, which four still frames did
    not show and the moving ones did."""
    assert P.Params().stage.font in (
        "Bradley Hand", "Marker Felt", "Chalkboard", "Noteworthy",
        "Brush Script MT", "Chalkduster")


def test_it_does_not_borrow_another_renderer():
    from pathlib import Path
    here = Path(types_mod.__file__).parent / "longhand"
    for name in ("build.py", "params.py", "field.py"):
        src = (here / name).read_text()
        for other in ("lyric_grid", "orbit", "swarm", "monument", "window"):
            assert f"from ..{other}" not in src, f"longhand/{name} imports {other}"


# ------------------------------------------------------------- the phrasing

def test_the_renderer_phrases_for_itself(lh):
    """Drawing one transcription line at a time is the obvious thing and it
    does not work: measured on a real song, 121 cues fall into 12 lines of 3 to
    32 words, the first spanning 11.4 seconds."""
    long_line = [(i * 0.4, "word%d" % i, 1) for i in range(32)]
    ps = lh._phrases(long_line)
    assert len(ps) > 1, "a 32-word line was left as one phrase"
    for p in ps:
        assert len(p) <= lh.MAX_WORDS, [c[1] for c in p]
        assert sum(len(c[1]) + 1 for c in p) - 1 <= lh.MAX_CHARS + lh.MAX_WORDS
        assert p[-1][0] - p[0][0] <= lh.MAX_SECONDS + 0.5


def test_phrases_are_near_equal_rather_than_greedy(lh):
    """A greedy split leaves a runt at the end of every line, and a gap
    threshold -- tried first -- orphans single words out of the middle:
    'Today' alone, 'across' alone, mean 2.2 words."""
    ps = lh._phrases([(i * 0.3, "wo", 1) for i in range(9)])
    sizes = [len(p) for p in ps]
    assert max(sizes) - min(sizes) <= 1, sizes


def test_a_phrase_never_spans_two_transcription_lines(lh):
    ps = lh._phrases(CUES)
    for p in ps:
        assert len({c[2] for c in p}) == 1, [c[1] for c in p]


def test_phrases_come_out_in_time_order(lh):
    starts = [p[0][0] for p in lh._phrases(CUES)]
    assert starts == sorted(starts)


def test_the_layout_is_computed_once(lh):
    assert lh._phrases(CUES) is lh._phrases(CUES)


# ------------------------------------------------- what reaches the screen

def test_the_phrase_being_sung_is_what_is_drawn(lh):
    ps = lh._phrases(CUES)
    bodies, _was, drawn, _g = lh._spec(ps, ps[0][0][0] + 0.1, 1.0)
    assert drawn > 1
    assert len(bodies) == len(lh.SIZES), "one Spec DAT per letter size"
    for b in bodies:
        assert b.split("\n")[0] == "x\ty\ttext"


def test_nothing_is_drawn_before_the_first_word(lh):
    ps = lh._phrases(CUES)
    _bodies, _was, drawn, _g = lh._spec(ps, ps[0][0][0] - 0.5, 1.0)
    assert drawn == 0


def test_a_phrase_clears_rather_than_sitting_through_an_instrumental(lh):
    """One gap in the benchmark song is 15.4 seconds. Holding a phrase across
    that is a frozen frame, not a lyric video."""
    ps = lh._phrases(CUES)
    last = ps[-1]
    assert lh._spec(ps, last[-1][0] + lh.LINGER * 0.5, 1.0)[2] > 0
    assert lh._spec(ps, last[-1][0] + lh.LINGER + 1.0, 1.0)[2] == 0


def test_the_block_is_written_from_the_lower_left(lh):
    """The Spec DAT's origin, and the thing that has cost time twice here.
    Written top-down the whole block renders upside down."""
    lh.CENTER_Y = 0.0          # the block at the TOP of the frame
    lh.WAVER = 0.0
    ps = lh._phrases(CUES)
    bodies, _was, _n, _g = lh._spec(ps, ps[0][0][0] + 0.1, 1.0)
    ys = [int(r.split("\t")[1]) for b in bodies for r in b.split("\n")[1:]]
    assert ys and min(ys) > lh.HEIGHT * 0.5, (
        "a block at the top of the frame should have a HIGH y in lower-left "
        "pixel coordinates")


def test_every_phrase_of_a_real_song_fits_inside_the_frame(lh):
    """A row that runs off the edge loses words, and nothing else would say so."""
    from pathlib import Path

    from lyricfield.cues import CueTable

    here = Path(types_mod.__file__).resolve().parents[1] / "data"
    cues = [(c.start, c.word, c.line)
            for c in CueTable.load(here / "preview_cues.tsv").cues]
    ps = lh._phrases(cues)
    assert ps
    for p in ps:
        bodies, _was, _n, _g = lh._spec(ps, p[0][0] + 0.01, 1.0)
        xs = [int(r.split("\t")[0]) for b in bodies for r in b.split("\n")[1:]]
        assert xs, [c[1] for c in p]
        assert min(xs) >= 0 and max(xs) <= lh.WIDTH - 10, (
            f"{' '.join(c[1] for c in p)!r} runs to x {max(xs)} of {lh.WIDTH}")


def test_a_long_phrase_wraps_into_rows(lh):
    lh.WAVER = 0.0
    ps = lh._phrases([(0.0, "extraordinarily", 1), (0.4, "long", 1),
                      (0.8, "wordy", 1), (1.2, "phrase", 1)])
    bodies, _was, _n, _g = lh._spec(ps, 0.1, 1.0)
    ys = {int(r.split("\t")[1]) for b in bodies for r in b.split("\n")[1:]}
    assert len(ys) > 1, "everything landed on one baseline"


# ---------------------------------------------------------------- the hand

def test_the_lettering_is_not_a_font(lh):
    """The signature. Uniform glyphs on a ruled baseline read as a caption; the
    reference has letters of different sizes and a baseline that wanders."""
    ps = lh._phrases(CUES)
    bodies, _was, _n, _g = lh._spec(ps, ps[0][0][0] + 0.1, 1.0)
    used = [i for i, b in enumerate(bodies) if len(b.split("\n")) > 1]
    assert len(used) > 1, f"every letter came out the same size ({used})"
    ys = [int(r.split("\t")[1]) for b in bodies for r in b.split("\n")[1:]]
    assert len(set(ys)) > len(set(y // 40 for y in ys)), "the baseline is ruled"


def test_letters_come_out_in_mixed_case(lh):
    """"I CAN'4 Stop", "you CAN't AFFORD" -- the most recognisable thing about
    the reference's lettering."""
    ps = lh._phrases(CUES)
    bodies, _was, _n, _g = lh._spec(ps, ps[0][0][0] + 0.1, 1.0)
    got = [r.split("\t")[2] for b in bodies for r in b.split("\n")[1:]]
    assert any(c.isupper() for c in got), "nothing was shouted"
    assert any(c.islower() for c in got), "everything was shouted"


def test_shout_at_zero_leaves_the_words_alone(lh):
    lh.SHOUT = 0.0
    ps = lh._phrases(CUES)
    bodies, _was, _n, _g = lh._spec(ps, ps[0][0][0] + 0.1, 1.0)
    got = [r.split("\t")[2] for b in bodies for r in b.split("\n")[1:]]
    assert not any(c.isupper() for c in got)


def test_the_hand_is_a_pure_function_of_the_letter(lh):
    """No RNG anywhere, so the same song letters the same way on any machine
    and a dropped frame or a seek changes nothing."""
    ps = lh._phrases(CUES)
    a = lh._spec(ps, 1.7, 1.0)
    b = lh._spec(ps, 1.7, 1.0)
    assert a == b
    assert lh._wobble(7, 2.0) == lh._wobble(7, 2.0)
    assert lh._wobble(7, 2.0) != lh._wobble(8, 2.0)


def test_the_sizes_match_what_the_build_bakes_in(lh):
    """`field` assigns letters from its list and `build` fixes each Text TOP's
    font size from its own. If they drifted a letter would be drawn at a size
    the layout never measured and the row would not close up."""
    assert list(lh.SIZES) == pytest.approx(P.hand_sizes(P.Params()), rel=1e-6)


def test_one_step_is_uniform_lettering():
    p = P.Params()
    p.hand.steps = 1
    assert P.hand_sizes(p) == [p.stage.size]
    p.hand.steps, p.hand.spread = 3, 0.0
    P.reconcile(p)
    assert p.hand.steps == 1, "three identical sizes is three TOPs for nothing"


# ---------------------------------------------------------------- the ground

def test_the_song_s_own_footage_is_used_when_there_is_some():
    cfg = Config(type="longhand")
    cfg.track.plate = "/clips/coast.mp4"
    specs = {s.name: s for s in network(cfg)}
    assert specs["plate"].type == "moviefileinTOP"
    assert specs["plate"].params["file"] == "/clips/coast.mp4"


def test_footage_of_any_shape_is_cropped_to_fill_the_frame():
    """A plate is whatever the user had -- 16:9 against a 9:16 frame, most
    likely. `fillmode` "outside" scales until it covers and trims the overflow,
    so it is never letterboxed and never squashed."""
    cfg = Config(type="longhand")
    cfg.track.plate = "/clips/coast.mp4"
    specs = {s.name: s for s in network(cfg)}
    assert specs["lh_fit"].params["fillmode"] == "outside"
    assert specs["lh_fit"].inputs == ["plate"]


def test_a_song_with_no_footage_gets_a_generated_stand_in():
    """Which is what every style preview records against: a preview carries
    nothing of whichever song is loaded."""
    specs = {s.name: s for s in network(Config(type="longhand"))}
    assert specs["plate"].type != "moviefileinTOP"
    assert "lh_soft" in specs, "the stand-in is not defocused"


def test_the_plate_is_brought_down_before_the_lettering_goes_on():
    """White marker over a bright sky needs the sky darkened. The reference
    does that rather than outlining the type, which would stop it looking
    drawn."""
    specs = {s.name: s for s in network(Config(type="longhand"))}
    assert specs["lh_dim"].params["opacity"] < 1.0
    assert specs["lh_over"].inputs == ["lh_ink", "lh_dim"]
    assert specs["lh_over"].params["operand"] == "over"


def test_a_bright_ground_against_pale_ink_is_refused():
    p = P.Params()
    p.ground.dim, p.beat.kick_lift = 0.0, 0.3
    assert any("past white" in m for m in p.validate())
    P.reconcile(p)
    assert p.validate() == []
    assert p.look.ink == pytest.approx(0.97), (
        "the lettering's brightness gave way; it is legibility, not taste")


def test_dark_ink_wants_a_BRIGHT_ground_rather_than_a_darker_one():
    """The contrast rule asked one way round for as long as the ink was always
    white. Blue marker on light paper is the same requirement mirrored, and a
    check that only knows how to darken would answer it by making the page
    black -- refusing the look rather than settling it."""
    p = P.Params()
    p.look.ink_hue, p.look.ink_sat = 0.62, 0.9      # a saturated blue
    p.ground.dim, p.beat.kick_lift = 0.5, 0.0       # a mid-grey page
    assert P.ink_luma(p.look) < 0.5, "this test needs dark ink to mean anything"
    assert any("read against the other" in m for m in p.validate())
    P.reconcile(p)
    assert p.validate() == [], p.validate()
    assert p.ground.dim < 0.5, (
        f"the page was darkened to {p.ground.dim} behind dark ink, which is "
        "the wrong direction")


# --------------------------------------------------------------- the network

def test_one_text_top_per_letter_size_in_each_of_two_banks():
    """Two banks, because two phrases are on screen during a hand-over and a
    Text TOP has ONE colour for its whole Specification DAT."""
    specs = network(Config(type="longhand"))
    texts = [s for s in specs if s.type == "textTOP"]
    steps = P.Params().hand.steps
    assert len(texts) == steps * 2, [s.name for s in texts]
    assert {t.params["specdat"] for t in texts} == (
        {f"spec{i}" for i in range(steps)}
        | {f"wasspec{i}" for i in range(steps)})


def test_a_bigger_letter_size_gets_a_bigger_font():
    specs = {s.name: s for s in network(Config(type="longhand"))}
    sizes = [specs[f"lh_text{i}"].params["fontsizex"]
             for i in range(P.Params().hand.steps)]
    assert sizes == sorted(sizes), sizes
    for px, want in zip(sizes, P.hand_sizes(P.Params())):
        assert px == pytest.approx(want, rel=1e-3)


def test_the_letters_sit_on_a_baseline_not_on_their_centres():
    """With centre alignment a bigger letter rides up and the line reads as
    bouncing rather than as drawn."""
    specs = {s.name: s for s in network(Config(type="longhand"))}
    for i in range(P.Params().hand.steps):
        assert specs[f"lh_text{i}"].params["aligny"] == "bottom"


def test_the_sizes_are_summed_before_they_are_taken_to_the_ink():
    """A composite `add` clamps at white on an 8-bit TOP, so scaling each layer
    first and adding second is what loses the brightness -- measured once at
    exactly 1/3 on a renderer whose every layer read 0.93 upstream."""
    specs = {s.name: s for s in network(Config(type="longhand"))}
    n = P.Params().hand.steps
    assert specs["lh_now"].inputs == [f"lh_text_sum{n - 1}"]
    for i in range(1, n):
        assert specs[f"lh_text_sum{i}"].params["operand"] == "add"
        assert "brightness1" not in specs[f"lh_text{i}"].params


def test_the_inline_text_is_cleared():
    """A Text TOP draws its own inline `text` and ignores its DAT while that is
    non-empty. It ships holding the word "derivative"."""
    specs = {s.name: s for s in network(Config(type="longhand"))}
    for i in range(P.Params().hand.steps):
        assert specs[f"lh_text{i}"].params["text"] == ""


def test_the_font_size_is_in_pixels_rather_than_points():
    specs = {s.name: s for s in network(Config(type="longhand"))}
    for i in range(P.Params().hand.steps):
        p = specs[f"lh_text{i}"].params
        assert p["fontsizexunit"] == "pixels" and p["fontsizeyunit"] == "pixels"


def test_nothing_may_exceed_white():
    specs = {s.name: s for s in network(Config(type="longhand"))}
    assert specs["lh_clamp"].params["operand"] == "minimum"
    assert specs["out"].inputs == ["lh_clamp"]


# ------------------------------------------------- where in the song this is

def test_it_opens_arrives_and_ends(lh):
    lh.KICK_IN, lh.HIGH_IN, lh.TAIL_END = 20.0, 40.0, 200.0
    lh.INTRO_OPEN, lh.ARRIVE, lh.OUTRO = 0.35, 0.88, 10.0
    assert lh._section_gain(5.0) < lh._section_gain(30.0) < lh._section_gain(60.0)
    assert lh._section_gain(199.5) < lh._section_gain(150.0)


def test_nothing_is_written_through_a_measured_silence(lh):
    lh.HOLD_WINDOWS = ((10.0, 20.0),)
    assert lh._held(15.0) is True
    assert lh._held(25.0) is False


def test_a_song_with_no_cues_does_not_raise(lh):
    ps = lh._phrases([])
    bodies, _was, drawn, _g = lh._spec(ps, 3.0, 1.0)
    assert drawn == 0 and set(bodies) == {"x\ty\ttext"}


# ------------------------------------------------------------- the defaults

def test_the_defaults_are_a_valid_config():
    assert P.Params().validate() == []


def test_no_two_sections_share_a_key():
    import collections
    p = P.Params()
    names = [f for sec in p.__dataclass_fields__
             for f in getattr(p, sec).__dataclass_fields__]
    dupes = [n for n, c in collections.Counter(names).items() if c > 1]
    assert not dupes, f"sections flatten into one dict; {dupes} would collide"


def test_the_field_defaults_agree_with_the_params(lh):
    """Two copies of the same numbers: the dataclass, and the fallbacks the
    field script uses when it cannot read its params DAT. A drift between them
    means a preview and a render disagree, silently -- which is how this one
    was found, by the sizes test failing after `stage.size` moved."""
    p = P.Params()
    for section in p.__dataclass_fields__:
        for key, val in vars(getattr(p, section)).items():
            if key not in lh.DEFAULTS:
                continue
            assert lh.DEFAULTS[key] == pytest.approx(val) if isinstance(
                val, float) else lh.DEFAULTS[key] == val, (
                f"{section}.{key}: params says {val!r}, "
                f"field.py's DEFAULTS says {lh.DEFAULTS[key]!r}")


# ---------------------------------------------------------------- the motion

def _steps(xy):
    """Frame-to-frame steps, and how often the direction reverses."""
    import math

    dx = [xy[i + 1][0] - xy[i][0] for i in range(len(xy) - 1)]
    dy = [xy[i + 1][1] - xy[i][1] for i in range(len(xy) - 1)]
    mag = sorted(math.hypot(a, b) for a, b in zip(dx, dy))
    rev = lambda d: (sum(1 for i in range(len(d) - 1) if d[i] * d[i + 1] < 0)
                     / float(len(d) - 1))
    return mag[len(mag) // 2], mag[-1], rev(dx), rev(dy)


def test_the_camera_moves_like_a_hand_rather_than_drifting(lh):
    """The measurement, not the adjective.

    Two earlier versions of this motion were wrong, and the second was wrong in
    KIND rather than in amount -- a smooth constant-velocity slide. Tracked off
    the reference at 25fps over 353 frame-to-frame steps of the lettering's
    centroid, while holding:

        median step   2.09px on a 320-wide sample = 0.65% of the frame width
        direction reverses between consecutive frames: 55% in x, 40% in y

    A drift never reverses; that is the whole difference, and it is why this
    test checks the reversal rate rather than the amplitude alone. The smooth
    slide is measured here too, so the test's power to tell them apart is
    demonstrated rather than assumed.
    """
    here = [lh._handheld(k / 25.0) for k in range(600)]
    med, peak, rx, ry = _steps(here)
    assert 0.004 < med / lh.WIDTH < 0.010, (
        f"median step {med:.2f}px is {med / lh.WIDTH * 100:.2f}% of the width; "
        "the reference holds at 0.65%")
    assert peak / lh.WIDTH < 0.03, f"peak step {peak:.1f}px is a jump, not a hand"
    for name, r in (("x", rx), ("y", ry)):
        assert 0.35 < r < 0.65, (
            f"direction reverses {r * 100:.0f}% of frames in {name}; the "
            "reference is 55% in x and 40% in y, a drift is 0%")

    # ... and what it is not. The motion this replaced, sampled the same way.
    slide = [(k / 25.0 * 0.065 * lh.WIDTH, k / 25.0 * 0.036 * lh.HEIGHT)
             for k in range(600)]
    _m, _p, sx, sy = _steps(slide)
    assert sx == 0.0 and sy == 0.0, (
        "a constant-velocity slide reversed, so this test cannot tell the two "
        "kinds of motion apart and proves nothing")


def test_a_phrase_flies_in_and_then_holds(lh):
    """At the hand-over the camera is still on the last phrase, so the new one
    is drawn well off its place and arrives over the whip."""
    i = 4
    hx, hy = lh._home(i)
    px, py = lh._home(i - 1)
    apart = ((px - hx) ** 2 + (py - hy) ** 2) ** 0.5
    assert apart > lh.WIDTH * 0.05, "the two phrases are written too close to tell"

    ax, ay = lh._slide(i, i, 0.0, 10.0)
    flew = ((ax - (hx - hx)) ** 2 + (ay - (hy - hy)) ** 2) ** 0.5
    assert flew > apart * 0.7, (
        f"the arriving phrase starts {flew:.0f}px out, against {apart:.0f}px "
        "between the two places -- it did not fly in")

    sx, sy = lh._slide(i, i, lh.WHIP * 1.2, 10.0)
    assert (sx ** 2 + sy ** 2) ** 0.5 < apart * 0.3, (
        f"still {(sx ** 2 + sy ** 2) ** 0.5:.0f}px out after the whip")


def test_the_outgoing_phrase_is_carried_off_by_the_same_move(lh):
    """One camera, two phrases on one sheet: the move that brings the new
    phrase in takes the old one out. "The words fly in and out of the screen."
    """
    i = 4
    near = lh._slide(i - 1, i, 0.0, 10.0)
    far = lh._slide(i - 1, i, lh.WHIP, 10.0)
    assert (far[0] ** 2 + far[1] ** 2) ** 0.5 > \
           (near[0] ** 2 + near[1] ** 2) ** 0.5 * 2.0, (
        f"the outgoing phrase went from {near} to {far}; it faded where it "
        "stood rather than leaving")


def test_the_camera_overshoots_its_target(lh):
    """A hand swung onto a phrase arrives slightly past it. A linear move --
    which is what `_settle` would be without this -- reads as a rail."""
    over = max(lh._settle(u / 200.0) for u in range(200))
    assert over > 1.01, f"peaked at {over:.4f}; it eased in rather than landing"
    assert over < 1.20, f"overshot by {(over - 1) * 100:.0f}%, which is a bounce"
    assert lh._settle(0.0) == 0.0 and lh._settle(1.0) == 1.0
    assert lh._settle(-3.0) == 0.0 and lh._settle(4.0) == 1.0


def test_the_camera_is_a_pure_function_of_index_age_and_time(lh):
    assert lh._slide(3, 3, 0.7, 12.0) == lh._slide(3, 3, 0.7, 12.0)
    assert lh._handheld(4.25) == lh._handheld(4.25)
    # Two moments of the same phrase differ: it is never still.
    assert lh._slide(3, 3, 1.0, 12.0) != lh._slide(3, 3, 1.0, 12.5)


def test_phrases_are_not_all_written_in_the_same_place(lh):
    """Without this the camera would have nowhere to move, and a hand-over
    would stack the outgoing phrase directly behind the incoming one."""
    starts = {lh._home(i) for i in range(8)}
    assert len(starts) >= 7, starts
    spread = max(s[0] for s in starts) - min(s[0] for s in starts)
    assert spread > lh.WIDTH * 0.1, spread
    lh.PLACE = 0.0
    assert lh._home(3) == (0.0, 0.0)


def test_a_phrase_is_never_still_on_screen(lh):
    """The thing that was missing, and the whole of what "the words just appear
    on screen" meant."""
    ps = lh._phrases(CUES)
    t0 = ps[0][0][0]
    at = []
    for dt in (0.05, 0.6, 1.2):
        bodies, _was, _n, _g = lh._spec(ps, t0 + dt, 1.0)
        xs = [int(r.split("\t")[0]) for b in bodies for r in b.split("\n")[1:]]
        ys = [int(r.split("\t")[1]) for b in bodies for r in b.split("\n")[1:]]
        at.append((min(xs), min(ys)))
    assert len({a[0] for a in at}) > 1 or len({a[1] for a in at}) > 1, (
        f"the phrase sat still: {at}")


def test_emphasis_picks_one_word_out_large(lh):
    """Two of the references set one word of a phrase big and the rest small.
    At 1 the picked word is drawn entirely from the largest step and everything
    else from the smallest."""
    lh.EMPHASIS = 1.0
    words = ["one", "two", "three", "four"]
    hot = lh._hot_word(2, len(words))
    assert 0 <= hot < len(words)
    letters, _w, _k, _wi = lh._set(" ".join(words), 0, 0, hot)
    steps, wi = {}, 0
    for _shown, pick, _adv in letters:
        if pick is None:
            wi += 1
        else:
            steps.setdefault(wi, set()).add(pick)
    assert steps[hot] == {len(lh.SIZES) - 1}, (
        f"the picked word came out at steps {steps[hot]}")
    for w, seen in steps.items():
        if w != hot:
            assert seen == {0}, f"word {w} came out at {seen}, not the smallest"


def test_emphasis_off_leaves_the_hand_scatter_alone(lh):
    """It is a look on top of the lettering, not a replacement for it."""
    lh.EMPHASIS = 0.0
    assert lh._hot_word(2, 4) == -1
    picks = {lh._step_for(k, 0, -1) for k in range(40)}
    assert len(picks) > 1, "the letters all came out at one size"


def test_a_word_picked_out_large_does_not_run_into_the_next(lh):
    """The row advances on the size each letter is DRAWN at. Advancing on the
    nominal size instead puts an emphasised word 11% over the one after it,
    and the overlap is the kind of thing that looks like a font problem."""
    lh.EMPHASIS = 1.0
    letters, wide, _k, _wi = lh._set("alpha beta gamma", 0, 0, 1)
    assert wide == pytest.approx(sum(a for _s, _p, a in letters))
    plain, flat, _k, _wi = lh._set("alpha beta gamma", 0, 0, -1)
    assert wide != pytest.approx(flat), (
        "the emphasised row set to the same width as the plain one, so the "
        "sizes are not reaching the layout")


def test_the_ink_is_white_until_it_is_tinted():
    """`_rgb` with no saturation is white, which is what the default is."""
    p = P.Params()
    assert (p.look.ink_hue, p.look.ink_sat) == (0.0, 0.0)
    assert B._rgb(p.look.ink_hue, p.look.ink_sat) == (1.0, 1.0, 1.0)
    blue = B._rgb(0.6, 0.8)
    assert blue[2] > blue[0] and blue[2] > blue[1], blue


def test_the_ink_colour_reaches_the_text_tops():
    """A tint that the Text TOPs never see is a knob that reports success and
    changes nothing -- which is what 45 of this project's first 51 pushed
    values did."""
    cfg = Config(type="longhand")
    cfg.params.look.ink_hue, cfg.params.look.ink_sat = 0.6, 0.8
    want = B._rgb(0.6, 0.8)
    texts = [o for o in B.network(cfg) if o.type == "textTOP"]
    assert texts
    for o in texts:
        assert o.params["fontcolorr"] == pytest.approx(round(want[0], 4))
        assert o.params["fontcolorb"] == pytest.approx(round(want[2], 4))


def test_a_row_that_fits_is_kept_inside_however_it_is_placed(lh):
    """A row placed off-centre and then indented can run out of the frame and
    lose its last word, which nothing downstream would report -- the picture
    would simply be missing a word and every check would pass."""
    lh.PLACE = 0.4
    lh.INDENT = 0.15
    lh.JITTER = lh.WAVER = 0.0
    ps = lh._phrases([(0.0, "wordy", 1), (0.4, "short", 1), (0.8, "line", 1)])
    for i in range(3):
        bodies, _w, _n, _g = lh._spec(ps, ps[0][0][0] + i * 0.3, 1.0)
        xs = [int(r.split("\t")[0]) for b in bodies for r in b.split("\n")[1:]]
        if xs:
            assert min(xs) >= 0 and max(xs) < lh.WIDTH, (min(xs), max(xs))


def test_a_word_too_wide_for_the_frame_overflows_evenly(lh):
    """One word longer than the frame cannot be wrapped at all. The reference
    lets such a word run off both edges rather than shoving it against one, and
    so does this -- but it must be centred, not pushed."""
    lh.PLACE = 0.4
    lh.INDENT = 0.0
    lh.JITTER = lh.WAVER = 0.0
    ps = lh._phrases([(0.0, "supercalifragilistic", 1)])
    bodies, _w, _n, _g = lh._spec(ps, 0.05, 1.0)
    xs = [int(r.split("\t")[0]) for b in bodies for r in b.split("\n")[1:]]
    assert xs and min(xs) < 0, "a word this wide should overflow"
    # Centred, so it hangs off both edges by the same amount. Measured through
    # `_set`, which is what the layout uses: the row's width is the sum of the
    # advances of the letters as DRAWN -- at their own size steps, and
    # capitalised where `shout` capitalised them -- not the nominal one.
    _letters, wide, _k, _wi = lh._set("supercalifragilistic", 0, 0, -1)
    assert min(xs) == pytest.approx((lh.WIDTH - wide) * 0.5, abs=2), (
        f"start {min(xs)}, centred would be {(lh.WIDTH - wide) * 0.5:.0f}")


def test_two_phrases_are_on_screen_during_a_hand_over(lh):
    """They OVERLAP. For about a quarter of a second the outgoing phrase is
    still up, faded, drifting away, while the incoming one comes up underneath
    -- which is what makes it a hand-over rather than a cut."""
    ps = lh._phrases(CUES)
    assert len(ps) > 1
    just_after = ps[1][0][0] + lh.FADE * 0.3
    now, was, drawn, ghost = lh._spec(ps, just_after, 1.0)
    assert drawn > 0, "nothing arrived"
    assert sum(len(b.split("\n")) - 1 for b in was) > 0, "nothing was leaving"
    assert 0.0 < ghost <= lh.GHOST, ghost


def test_the_outgoing_phrase_is_gone_once_the_fade_is_over(lh):
    ps = lh._phrases(CUES)
    _now, was, _d, ghost = lh._spec(ps, ps[1][0][0] + lh.FADE + 0.2, 1.0)
    assert ghost == 0.0
    assert sum(len(b.split("\n")) - 1 for b in was) == 0


def test_the_first_phrase_has_nothing_behind_it(lh):
    ps = lh._phrases(CUES)
    _now, was, _d, ghost = lh._spec(ps, ps[0][0][0] + 0.05, 1.0)
    assert ghost == 0.0 and sum(len(b.split("\n")) - 1 for b in was) == 0


def test_rows_are_stacked_ragged_rather_than_centred(lh):
    """"that I KNOW" / "you CAN't" / "AFFOrD" each start about 0.04 of the
    frame right of the one above. Hand-placed, not set."""
    lh.JITTER = lh.WAVER = 0.0
    lh.PLACE = lh.SWAY = lh.TREMOR = 0.0          # hold the camera still
    ps = lh._phrases([(0.0, "extraordinarily", 1), (0.3, "long", 1),
                      (0.6, "wordy", 1), (0.9, "phrase", 1)])
    bodies, _w, _n, _g = lh._spec(ps, 0.05, 1.0)
    rows = {}
    for b in bodies:
        for r in b.split("\n")[1:]:
            x, y, _ = r.split("\t")
            rows.setdefault(int(y), []).append(int(x))
    assert len(rows) > 1, "only one row to compare"
    tops = [min(rows[y]) for y in sorted(rows, reverse=True)]
    assert tops == sorted(tops), f"rows are not indented rightwards: {tops}"
    assert tops[-1] - tops[0] >= lh.INDENT * lh.WIDTH * 0.5, tops


def test_the_outgoing_bank_has_its_own_brightness():
    """One Text TOP has one colour for its whole table, so the two phrases
    cannot share a bank."""
    specs = {s.name: s for s in network(Config(type="longhand"))}
    assert specs["lh_ghost"].params["brightness1"] == 0.0, (
        "with nothing leaving, nothing should show")
    assert specs["lh_ink"].inputs == ["lh_now", "lh_ghost"]
    assert specs["lh_ink"].params["operand"] == "add"
