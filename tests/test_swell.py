"""The second beatsync renderer: the beat as weight, not brightness.

`pulse_grid` proves a song with no words is a song. `swell` proves it can be
made a second way -- and it is the first renderer of any family to read
`kick_in`, `high_in` and `duration`, which every beatsync type had been binding
into its defaults and never looking at, so the piece had no beginning, no
arrival and no ending.

The field script imports standalone for the same reason the other two do, so
what it draws is testable with no TouchDesigner.
"""

from __future__ import annotations

import types as pytypes
from pathlib import Path

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.types.swell import params as P

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def sw():
    src = (REPO / "lyricfield" / "types" / "swell" / "field.py").read_text()
    mod = pytypes.ModuleType("swell_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    mod.S["rng"] = np.random.default_rng(7)
    mod._init()
    return mod


def _cover_at(mod, t, **kw):
    """Occupied cells at t, with no drums unless asked for."""
    return int((mod._weights(t, **kw) > 0).sum())


def _at_phase(mod, around, frac=None):
    """The nearest time to `around` sitting at the same point in the bar.

    Coverage moves within every bar, so comparing two arbitrary timestamps
    measures the bar phase, not the thing under test. The first version of
    `test_it_actually_ends` did exactly that and reported the outro as *denser*
    than the body.
    """
    span = mod.BEAT * mod.BAR_BEATS
    frac = mod.ATTACK if frac is None else frac
    n = round((around - mod.BEAT_ANCHOR - span * frac) / span)
    return mod.BEAT_ANCHOR + span * (n + frac)


# ----------------------------------------------------------------- the type

def test_it_is_registered_as_a_second_beatsync_type():
    vt = types_mod.get_type("swell")
    assert vt.family == types_mod.BEATSYNC
    assert vt.needs_lyrics is False
    others = [t.slug for t in types_mod.list_types()
              if t.family == types_mod.BEATSYNC and t.slug != "swell"]
    assert others, "swell is meant to be a *second* beatsync renderer"


def test_it_does_not_ask_for_stem_separation():
    vt = types_mod.get_type("swell")
    assert types_mod.VOCALS not in vt.needs
    assert types_mod.CUES not in vt.needs


def test_defaults_are_valid():
    assert P.Params().validate() == []


def test_it_measures_the_same_regions_as_the_other_types():
    assert set(P.Params().regions()) == {"band", "lower"}


# ------------------------------------------------------------- validation

def test_a_glyph_ramp_of_one_character_is_refused():
    """With one glyph there is no ramp, and the whole renderer is its ramp."""
    p = P.Params()
    p.swell.glyphs = "#"
    assert p.validate() != []


def test_inverted_coverage_bounds_are_refused():
    p = P.Params()
    p.swell.open_min, p.swell.open_max = 0.8, 0.2
    assert p.validate() != []


def test_a_threshold_nothing_can_reach_is_refused():
    """Weight tops out at 1.0, so lit_at at or above it lights nothing ever."""
    p = P.Params()
    p.swell.lit_at = 1.0
    assert p.validate() != []


def test_a_zero_length_bar_is_refused():
    p = P.Params()
    p.swell.bar_beats = 0.0
    assert p.validate() != []


# --------------------------------------------------------------- the field

def test_the_fallback_defaults_are_not_a_song(sw):
    d = sw.DEFAULTS
    assert d["duration"] == 0.0
    assert d["kick_in"] == 0.0
    assert not d["hold_windows"]
    assert d["beat_period"] > 0, "a zero period divides by zero every frame"


def test_a_missing_params_dat_is_recorded(sw):
    sw._load_params()
    assert sw.PARAMS_MISSING is True


def test_the_field_thickens_on_the_downbeat_and_thins_across_the_bar(sw):
    """The whole renderer in one measurement: coverage rises fast, falls slow."""
    span = sw.BEAT * sw.BAR_BEATS
    trough = _cover_at(sw, sw.BEAT_ANCHOR + span * 0.999)
    crest = _cover_at(sw, sw.BEAT_ANCHOR + span * sw.ATTACK)
    mid = _cover_at(sw, sw.BEAT_ANCHOR + span * 0.55)
    assert crest > mid > trough, f"crest {crest}, mid {mid}, trough {trough}"


def test_it_is_the_glyph_that_changes_not_the_brightness(sw):
    """`pulse_grid` moves light; this moves weight. The mean position on the
    ramp must rise on the beat while the brightest cell does not move."""
    span = sw.BEAT * sw.BAR_BEATS
    steps = len(sw.RAMP) - 1

    def rank_and_peak(t):
        w = sw._weights(t)
        drawn = w[w > 0]
        idx = np.rint(w * steps)
        v = sw.LEVEL_MIN + (sw.LEVEL_MAX - sw.LEVEL_MIN) * w
        return (idx[w > 0].mean() if drawn.size else 0.0), float(v.max())

    heavy, peak_hi = rank_and_peak(sw.BEAT_ANCHOR + span * sw.ATTACK)
    light, peak_lo = rank_and_peak(sw.BEAT_ANCHOR + span * 0.999)
    assert heavy > light, "glyphs do not step up the ramp on the beat"
    assert peak_hi <= sw.LEVEL_MAX + 1e-6 and peak_lo <= sw.LEVEL_MAX + 1e-6


def test_nothing_it_draws_can_breach_the_stacking_rule(sw):
    """The point of expressing the beat as coverage: the dim layer never leaves
    its own band, whatever the drums do, so nothing can clip at the output."""
    span = sw.BEAT * sw.BAR_BEATS
    peak = 0.0
    for i in range(40):
        t = sw.BEAT_ANCHOR + span * i / 40.0
        w = sw._weights(t, kick=1.0, snare=1.0, high=1.0)
        peak = max(peak, float((sw.LEVEL_MIN +
                                (sw.LEVEL_MAX - sw.LEVEL_MIN) * w).max()))
    assert peak <= sw.LEVEL_MAX + 1e-6
    assert sw.LEVEL_MAX <= sw.CEIL


def test_a_kick_fills_blanks_in_rather_than_only_lighting_cells(sw):
    """The ring must recruit cells that were carrying nothing."""
    t = sw.BEAT_ANCHOR + sw.BEAT * sw.BAR_BEATS * 0.9   # a thin moment
    quiet = _cover_at(sw, t)
    sw.S["beat_i"] = -1
    loud = _cover_at(sw, t, kick=1.0)
    assert loud > quiet, f"kick added no coverage ({quiet} -> {loud})"


def test_a_snare_puts_cells_at_the_top_of_the_ramp(sw):
    t = sw.BEAT_ANCHOR + sw.BEAT * sw.BAR_BEATS * 0.9
    before = sw._weights(t)
    after = sw._weights(t, snare=1.0)
    assert after.max() > before.max()
    assert after.max() >= sw.LIT_AT, "a snare never reaches the bold layer"


def test_hold_windows_freeze_the_beat_response(sw):
    """Digital silence is a splice point; the field holds its breath rather
    than firing at nothing."""
    sw.HOLD_WINDOWS = ((5.0, 8.0),)
    assert sw._held(6.0) is True
    assert sw._held(4.0) is False
    held = sw._weights(6.0, kick=1.0, snare=1.0, high=1.0)
    plain = sw._weights(6.0)
    assert np.allclose(held, plain), "the drums still moved it inside a hold"


# ---------------------------------------------- the three neglected facts

def test_it_is_sparser_before_the_drums_enter(sw):
    sw.KICK_IN, sw.HIGH_IN, sw.TAIL_END = 20.0, 40.0, 200.0
    intro = _cover_at(sw, _at_phase(sw, 6.0))
    body = _cover_at(sw, _at_phase(sw, 60.0))
    assert intro < body, f"intro {intro} is not sparser than the body {body}"


def test_it_opens_up_when_the_hi_hats_arrive(sw):
    sw.KICK_IN, sw.HIGH_IN, sw.TAIL_END = 20.0, 40.0, 200.0
    assert sw._section_gain(30.0) < sw._section_gain(60.0)


def test_it_actually_ends(sw):
    """Without an outro the piece simply stops mid-bar on the last frame."""
    sw.KICK_IN, sw.HIGH_IN, sw.TAIL_END = 20.0, 40.0, 200.0
    body = _cover_at(sw, _at_phase(sw, 100.0))
    late = _cover_at(sw, _at_phase(sw, sw.TAIL_END - sw.OUTRO * 0.4))
    end = _cover_at(sw, _at_phase(sw, sw.TAIL_END - 0.2))
    assert body > late > end, f"body {body}, late {late}, end {end}"
    assert end == 0, "the field is still occupied on the last frame"


def test_a_song_with_no_measured_kick_is_not_given_an_invented_intro(sw):
    """A fallback that is convincingly wrong is worse than one that is
    obviously wrong: with nothing measured, play it flat."""
    sw.KICK_IN, sw.HIGH_IN, sw.TAIL_END = 0.0, 0.0, 0.0
    assert sw._section_gain(0.5) == pytest.approx(1.0)
    assert sw._section_gain(500.0) == pytest.approx(1.0)
