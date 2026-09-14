"""Glitch: the words, torn.

Two things here are easy to get wrong in ways that look like a style choice
rather than a bug. The tear has to be a *hard* per-block displacement -- a
smooth one is a wobble, and wobble reads as "wavy text effect" rather than as a
damaged signal. And the map has to be a pure function of its own timestamp, or
the piece does not render the same way twice, which is the rule CLAUDE.md sets
for every renderer that has a choice.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.config import Config
from lyricfield.types.glitch import params as P
from lyricfield.types.glitch.build import network


@pytest.fixture
def cooker_glitch(gl):
    """Drive `onCook` and hand back the array it emitted.

    The map is the renderer's entire output, so the only honest place to ask
    about its orientation is after the flip that `copyNumpyArray` is given.
    """
    import numpy as np

    class _Cell:
        def __init__(self, v):
            self.val = v

    class _DAT:
        def __init__(self, rows=()):
            self.rows = [list(r) for r in rows]
            self.text = ""

        @property
        def numRows(self):
            return len(self.rows)

        def __getitem__(self, rc):
            r, c = rc
            row = self.rows[r]
            return _Cell(row[c] if c < len(row) else "")

    class _ScriptOp:
        def __init__(self):
            self.frame = None

        def copyNumpyArray(self, a):
            self.frame = a

    def cook(t=2.0, **params):
        dats = {"lyrics": _DAT([("word", "start", "line"),
                                ("hold", "1.0", "1")]),
                "drums": _DAT([("kind", "start_seconds")]),
                "gl_words": _DAT(), "params": _DAT()}
        gl.__dict__["op"] = lambda p: dats.get(p)
        gl.__dict__["me"] = pytest.importorskip("types").SimpleNamespace(
            time=pytest.importorskip("types").SimpleNamespace(seconds=t))
        gl.__dict__["root"] = pytest.importorskip("types").SimpleNamespace(
            time=pytest.importorskip("types").SimpleNamespace(
                seconds=t, end=3600.0, rate=60.0))
        gl.__dict__["CookLevel"] = type("C", (), {"ALWAYS": 1})
        if params:
            gl.DEFAULTS.update(params)
        gl._apply_params()
        gl.S.clear()
        sop = _ScriptOp()
        gl.onCook(sop)
        return sop.frame, gl.S.get("stats", {})

    return cook


@pytest.fixture
def gl():
    src = types_mod.get_type("glitch").field_source()
    mod = pytypes.ModuleType("glitch_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    mod._apply_params()
    mod.S["rows_h"] = None
    return mod


# ----------------------------------------------------------------- the type

def test_it_is_a_lyric_type_that_needs_words():
    vt = types_mod.get_type("glitch")
    assert vt.family == types_mod.LYRIC
    assert vt.needs_lyrics is True


def test_it_does_not_borrow_another_renderer():
    from pathlib import Path
    here = Path(types_mod.__file__).parent / "glitch"
    for name in ("build.py", "params.py", "field.py"):
        src = (here / name).read_text()
        for other in ("lyric_grid", "orbit", "swarm", "monument", "window"):
            assert f"from ..{other}" not in src, f"glitch/{name} imports {other}"


# --------------------------------------------------------------- the tear

def test_a_torn_row_jumps_rather_than_slides(gl):
    """The displacement has to be piecewise constant. A smooth one is a wobble,
    and a wobble is a different effect entirely."""
    gl.REST, gl.KICK_LIFT, gl.CHURN = 1.0, 0.0, 0.0
    shift = gl._tear(1.0)
    steps = np.unique(np.round(shift, 6))
    # A band of 0.06 over 1280 rows is about 21 blocks, so far fewer distinct
    # values than rows.
    assert len(steps) < gl.HEIGHT / 8, len(steps)


def test_rows_inside_one_block_move_together(gl):
    gl.REST, gl.KICK_LIFT, gl.CHURN = 1.0, 0.0, 0.0
    gl.BAND = 0.1                      # 128-row blocks at 1280 high
    shift = gl._tear(1.0)
    assert shift[10] == shift[11] == shift[12]


def test_nothing_tears_when_nothing_is_asked_for(gl):
    gl.REST, gl.KICK_LIFT = 0.0, 0.0
    assert not np.any(gl._tear(1.0))


def test_a_kick_tears_more_of_the_frame(gl):
    gl.REST, gl.KICK_LIFT, gl.KICK_TIME, gl.CHURN = 0.05, 0.9, 0.2, 0.0
    quiet = np.count_nonzero(gl._tear(10.0))
    gl.S["kick_t"] = 10.0
    loud = np.count_nonzero(gl._tear(10.0))
    assert loud > quiet


def test_the_tear_is_the_same_at_the_same_moment(gl):
    """A pure function of its own timestamp. Drawing random numbers per frame
    would make a dropped frame or a seek change what is rendered, and the piece
    would not render the same way twice."""
    gl.REST, gl.CHURN = 0.4, 9.0
    a = gl._tear(3.25)
    b = gl._tear(3.25)
    assert np.array_equal(a, b)


def test_the_tear_reshuffles_as_time_passes(gl):
    gl.REST, gl.CHURN = 0.4, 9.0
    a = gl._tear(3.0)
    b = gl._tear(3.6)
    assert not np.array_equal(a, b)


def test_churn_of_zero_holds_one_pattern(gl):
    gl.REST, gl.CHURN = 0.4, 0.0
    assert np.array_equal(gl._tear(1.0), gl._tear(9.0))


# ------------------------------------------------------------- the scanlines

def test_scanlines_darken_without_going_black(gl):
    gl.DEPTH, gl.HAT_LIFT = 0.35, 0.0
    m = gl._scan(0.0)
    assert m.max() <= 1.0 + 1e-6
    assert m.min() > 0.0, "fully black lines make the type unreadable"


def test_the_hats_deepen_the_scanlines(gl):
    gl.DEPTH, gl.HAT_LIFT, gl.HAT_TIME = 0.2, 0.5, 0.2
    quiet = float(gl._scan(10.0).min())
    gl.S["hat_t"] = 10.0
    loud = float(gl._scan(10.0).min())
    assert loud < quiet


def test_scanlines_that_would_reach_full_black_are_refused():
    p = P.Params()
    p.lines.depth, p.lines.hat_lift = 0.9, 0.5
    assert any("full black" in m for m in p.validate())
    P.reconcile(p)
    assert p.validate() == [], p.validate()


# ------------------------------------------------------------ the map itself

def test_the_map_samples_the_row_it_is_on(gl):
    """Green carries the vertical coordinate and the tear is sideways only, so
    a row must sample its own height. Letting it drift vertically smears the
    type up the frame."""
    h = gl.HEIGHT
    ys = (np.arange(h, dtype=np.float32) + 0.5) / h
    assert ys[0] < ys[-1]
    assert ys[0] == pytest.approx(0.5 / h)


def test_the_map_is_linear_across_its_width(gl):
    """The whole reason an eight-pixel-wide map is exact rather than
    approximate: the sampled coordinate is linear in x, so interpolating back
    up to frame width introduces no error."""
    xs = (np.arange(gl.MAP_W, dtype=np.float32) + 0.5) / gl.MAP_W
    d = np.diff(xs)
    assert np.allclose(d, d[0])


# -------------------------------------------------------------- the words

def test_the_line_assembles_as_it_is_sung(gl):
    gl.HOLD = 10.0
    cues = [(1.0, "hold", 1), (1.5, "on", 1), (2.0, "to", 1), (9.0, "next", 2)]
    assert gl._line_at(cues, 1.2) == "hold"
    assert gl._line_at(cues, 1.7) == "hold on"
    assert gl._line_at(cues, 2.2) == "hold on to"


def test_a_new_line_clears_the_one_before(gl):
    gl.HOLD = 10.0
    cues = [(1.0, "first", 1), (2.0, "second", 2)]
    assert gl._line_at(cues, 2.5) == "second"


def test_a_word_drops_out_after_its_hold(gl):
    gl.HOLD = 0.5
    cues = [(1.0, "gone", 1), (1.2, "here", 1)]
    assert gl._line_at(cues, 1.6) == "here"


# -------------------------------------------------- where in the song this is

def test_it_opens_arrives_and_ends(gl):
    gl.KICK_IN, gl.HIGH_IN, gl.TAIL_END = 20.0, 40.0, 200.0
    gl.INTRO_OPEN, gl.ARRIVE, gl.OUTRO = 0.3, 0.85, 10.0
    assert gl._section_gain(5.0) < gl._section_gain(30.0) < gl._section_gain(60.0)


def test_nothing_is_drawn_through_a_measured_silence(gl):
    gl.HOLD_WINDOWS = ((10.0, 20.0),)
    assert gl._held(15.0) is True
    assert gl._held(25.0) is False


def test_an_envelope_is_clamped_at_both_ends(gl):
    assert 0.0 <= gl._env(1.0, struck=5.0, decay=0.3) <= 1.0
    assert gl._env(5.0, struck=5.0, decay=0.3) == pytest.approx(1.0)
    assert gl._env(9.0, struck=5.0, decay=0.3) == pytest.approx(0.0)


# ---------------------------------------------------------------- the network

def test_the_remap_reads_the_map_from_the_script_top():
    specs = {s.name: s for s in network(Config(type="glitch"))}
    r = specs["gl_remap"]
    assert r.type == "remapTOP"
    assert r.inputs == ["gl_text", "v7_script"], (
        "input1 is the picture and input2 is the map; swapping them remaps the "
        "map through the text")
    assert r.params["horzsource"] == "red"
    assert r.params["vertsource"] == "green"


def test_the_split_takes_its_three_channels_from_three_places():
    """A Reorder TOP has four inputs, which is why this is one operator."""
    specs = {s.name: s for s in network(Config(type="glitch"))}
    r = specs["gl_split"]
    assert r.inputs == ["gl_plus", "gl_remap", "gl_minus"]
    assert r.params["outputred"] == "input1"
    assert r.params["outputgreen"] == "input2"
    assert r.params["outputblue"] == "input3"
    assert r.params["outputalpha"] == "input2", (
        "alpha from a shifted copy makes the type's silhouette lurch")


def test_the_map_is_eight_pixels_wide_and_the_full_height():
    cfg = Config(type="glitch")
    specs = {s.name: s for s in network(cfg)}
    p = specs["v7_script"].params
    assert p["resolutionw"] == 8
    assert p["resolutionh"] == cfg.params.stage.height


def test_the_inline_text_is_cleared():
    """A Text TOP draws its own inline `text` and ignores its DAT while that is
    non-empty. It ships holding the word "derivative"."""
    specs = {s.name: s for s in network(Config(type="glitch"))}
    assert specs["gl_text"].params["text"] == ""


def test_the_font_size_is_in_pixels_rather_than_points():
    specs = {s.name: s for s in network(Config(type="glitch"))}
    p = specs["gl_text"].params
    assert p["fontsizexunit"] == "pixels" and p["fontsizeyunit"] == "pixels"


def test_the_ink_colour_reaches_the_type():
    cfg = Config(type="glitch")
    cfg.params.look.hue, cfg.params.look.sat = 0.0, 1.0      # pure red
    specs = {s.name: s for s in network(cfg)}
    p = specs["gl_text"].params
    assert p["fontcolorr"] > p["fontcolorg"]
    assert p["fontcolorr"] > p["fontcolorb"]


# ------------------------------------------------------------- the defaults

def test_the_defaults_are_a_valid_config():
    assert P.Params().validate() == []


def test_tearing_the_whole_frame_at_once_is_refused():
    p = P.Params()
    p.tear.rest, p.tear.kick_lift = 0.6, 0.8
    assert any("whole frame" in m for m in p.validate())
    P.reconcile(p)
    assert p.validate() == [], p.validate()
    assert p.tear.rest == pytest.approx(0.6), (
        "the style's own resting damage gave way; only the loud part should")


def test_no_two_sections_share_a_key():
    """`sections.flatten()` merges every section into ONE dict, so two sections
    with the same key silently keep whichever came last. `tear.rest` and a
    `split.rest` collided here while this was being written."""
    import collections
    p = P.Params()
    names = [f for sec in p.__dataclass_fields__
             for f in getattr(p, sec).__dataclass_fields__]
    dupes = [k for k, n in collections.Counter(names).items() if n > 1]
    assert not dupes, dupes


def test_the_map_tells_each_row_to_sample_itself(cooker_glitch):
    """A TOP's row 0 is the BOTTOM of the frame, and the whole map is flipped on
    the way out. Written the obvious way up, the map told the bottom of the
    frame to sample the top and every glyph rendered upside down -- which reads
    as a broken renderer, not as an axis mistake.

    Asked of the array the Script TOP actually emits, after the flip.
    """
    import numpy as np

    frame, _ = cooker_glitch(t=2.0, rest=0.0, kick_lift=0.0)
    green = frame[:, 0, 1]
    # In TD orientation row 0 is the bottom and v must rise with the row index.
    assert green[0] < green[-1], (
        "the map is upside down: the bottom of the frame samples the top")
    assert green[0] == pytest.approx(0.5 / frame.shape[0], abs=1e-4)
    assert green[-1] == pytest.approx(1.0 - 0.5 / frame.shape[0], abs=1e-4)


def test_an_untorn_row_samples_straight_across(cooker_glitch):
    import numpy as np

    frame, _ = cooker_glitch(t=2.0, rest=0.0, kick_lift=0.0)
    red = frame[0, :, 0]
    assert np.all(np.diff(red) > 0), "the horizontal map must run left to right"
    assert red[0] > 0.0 and red[-1] < 1.0
