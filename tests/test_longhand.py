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
    assert any("read over it" in m for m in p.validate())
    P.reconcile(p)
    assert p.validate() == []
    assert p.look.ink == pytest.approx(0.97), (
        "the lettering's brightness gave way; it is legibility, not taste")


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

def test_a_phrase_drifts_the_whole_time_it_is_up(lh):
    """The thing that was missing, and the whole of what "the words just appear
    on screen" meant.

    In the reference a phrase is never still. Measured off the video by
    tracking the lettering's centroid on dark aerial plates, over four separate
    phrases: 0.022, 0.031, 0.036 and 0.093 frame-widths per second.
    """
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
    # ... and it goes one way, rather than wobbling in place
    drift = abs(at[2][0] - at[0][0]) + abs(at[2][1] - at[0][1])
    assert drift > 8, f"drifted only {drift}px over 1.15s"


def test_consecutive_phrases_do_not_slide_the_same_way(lh):
    """The direction is a pure function of the phrase's index, so the frame
    does not develop a single prevailing wind."""
    ways = {tuple(round(v, 2) for v in lh._slide(i, 1.0)) for i in range(8)}
    assert len(ways) >= 6, ways


def test_the_drift_is_a_pure_function_of_index_and_age(lh):
    assert lh._slide(3, 0.7) == lh._slide(3, 0.7)
    # At zero age a phrase is at its OWN starting place, which is not the
    # centre -- that offset is what keeps a hand-over from stacking the
    # outgoing phrase directly behind the incoming one.
    assert lh._slide(3, 0.0) != (0.0, 0.0)
    lh.PLACE = 0.0
    assert lh._slide(3, 0.0) == (0.0, 0.0)


def test_phrases_do_not_all_start_in_the_same_place(lh):
    """Without this, during a hand-over the outgoing phrase sits directly
    behind the incoming one and the pair reads as mud."""
    starts = {lh._slide(i, 0.0) for i in range(8)}
    assert len(starts) >= 7, starts
    spread = max(s[0] for s in starts) - min(s[0] for s in starts)
    assert spread > lh.WIDTH * 0.1, spread


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
    # Centred, so it hangs off both edges by the same amount. Asserted on the
    # row's own start rather than reconstructed from letter positions -- the
    # last letter's width is its own advance, not the nominal size.
    wide = lh._measure("supercalifragilistic")
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
    lh.RATE = 0.0
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
