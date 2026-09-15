"""What a drum does to the words.

Seven renderers were built on the premise that a beat look is a *picture* to put
behind the type. It is not: what was wanted is the beat visible in the text
itself. So there is one chain on the word layer and a preset is a set of
numbers, which is what makes every effect work with every word look.

The tests worth having are about the *feel*, because that is the thing being
asked for and the thing a comment cannot hold. "Floaty, moving, organic" is not
a mood here, it is four measurable properties of the envelope, and a linear
`1 - age/decay` -- which is what every other renderer in this project used --
fails all four.
"""

from __future__ import annotations

import math
import types as pytypes

import numpy as np
import pytest

from lyricfield import beat
from lyricfield import compose
from lyricfield import types as types_mod
from lyricfield.config import Config

PRESETS = [p[0] for p in beat.PRESETS]
RENDERERS = [t.slug for t in types_mod.list_types()]


# ------------------------------------------------- floaty, moving, organic

def _curve(decay=0.45, bounce=beat.impulse.__defaults__[0], n=400):
    """The response sampled densely over one strike, from t=1.0."""
    return [(i * decay * 1.4 / n,
             beat.impulse(1.0 + i * decay * 1.4 / n, 1.0, decay, bounce))
            for i in range(n)]


def test_the_attack_is_fast_and_the_release_is_slow():
    """A symmetric envelope reads as a fade. The asymmetry is what makes it
    read as a strike."""
    c = _curve()
    peak_at = max(c, key=lambda p: p[1])[0]
    # Back to near-rest
    rest_at = next(t for t, v in c if t > peak_at and abs(v) < 0.02)
    assert peak_at < 0.06, f"attack took {peak_at * 1000:.0f}ms"
    assert rest_at > peak_at * 4, (
        f"release {rest_at:.3f}s is not slow against a {peak_at:.3f}s attack")


def test_it_overshoots_its_rest_point_and_comes_back():
    """The whole difference between struck and faded. A damped spring crosses
    zero and swings back; a decay never does."""
    vals = [v for _, v in _curve()]
    assert max(vals) > 0.98, "never reached full"
    assert min(vals) < -0.02, (
        f"never crossed rest (min {min(vals):.3f}); this is a decay, not a spring")
    assert abs(vals[-1]) < 0.02, "did not settle"


def test_the_overshoot_can_be_turned_off():
    """An effect that must not go below rest -- a blur radius, say -- needs a
    plain decay, so `bounce=0` has to be a real option rather than a fudge."""
    vals = [v for _, v in _curve(bounce=0.0)]
    assert min(vals) >= 0.0
    assert max(vals) > 0.98


def test_nothing_is_ever_perfectly_still():
    """A layer that freezes between hits makes every hit read as a stutter.
    The drift is what keeps it moving."""
    vals = [beat.drift(t) for t in np.arange(0.0, 20.0, 0.05)]
    assert max(vals) > 0.3 and min(vals) < -0.3, "the drift barely moves"
    assert all(abs(v) <= 1.0 for v in vals), "the drift left its range"
    # Distinct at every sample: a constant, or a period short enough to see
    # repeat, would both fail this.
    assert len(set(round(v, 6) for v in vals)) > len(vals) * 0.9


def test_the_drift_does_not_visibly_repeat():
    """Three incommensurable periods, so the sum has no short common multiple.
    One sine would loop every few seconds and read as a wobble."""
    a = np.array([beat.drift(t) for t in np.arange(0.0, 30.0, 0.1)])
    b = np.array([beat.drift(t + 12.0) for t in np.arange(0.0, 30.0, 0.1)])
    assert float(np.abs(a - b).mean()) > 0.15, "the drift repeats within 12s"


def test_the_envelope_is_a_pure_function_of_its_timestamp():
    """No per-frame integration anywhere, so a dropped frame or a seek cannot
    change what is drawn and the song renders the same way twice."""
    assert beat.impulse(1.2, 1.0, 0.4) == beat.impulse(1.2, 1.0, 0.4)
    assert beat.drift(7.3) == beat.drift(7.3)


# ------------------------------------------------------------ the clamping

def test_a_strike_ahead_of_the_playhead_is_not_a_response():
    """A seek makes this routine, and an unclamped `1 - age/decay` is then
    greater than one and grows without limit -- measured once at 0.86 of white
    across a whole field, with everything else invisible inside it."""
    assert beat.impulse(1.0, struck=5.0, decay=0.4) == 0.0


def test_a_strike_long_past_is_not_a_response():
    assert beat.impulse(99.0, struck=1.0, decay=0.4) == 0.0


def test_the_response_never_exceeds_one():
    for decay in (0.1, 0.45, 2.0):
        for i in range(500):
            v = beat.impulse(1.0 + i * decay / 250, 1.0, decay)
            assert -1.0 <= v <= 1.0, (decay, v)


# ------------------------------------------------------------- the presets

@pytest.mark.parametrize("slug", PRESETS)
def test_every_preset_is_valid(slug):
    assert beat.preset(slug).validate() == []


@pytest.mark.parametrize("slug", PRESETS)
def test_every_preset_reconciles_to_something_valid(slug):
    r = beat.preset(slug)
    r.zoom.amount = 99.0           # whatever a hand-edit might do
    r.shake.amount = -1.0
    r.bloom.lift = 9.0
    beat.reconcile(r)
    assert r.validate() == [], r.validate()


def test_none_switches_everything_off():
    assert beat.preset("none").active() == []


def test_the_presets_are_not_all_the_same():
    """Five tiles that do the same thing is the duplicate-gallery problem in a
    new place."""
    seen = {s: repr(sorted(vars(beat.preset(s)).items(), key=str))
            for s in PRESETS}
    assert len(set(seen.values())) == len(seen)


def test_each_preset_leads_with_a_different_shape():
    """Not just different numbers -- a different combination of effects, or the
    row is five names for one look."""
    shapes = {s: tuple(beat.preset(s).active()) for s in PRESETS}
    assert len(set(shapes.values())) == len(shapes), shapes


def test_an_unknown_preset_is_refused_rather_than_guessed():
    with pytest.raises(KeyError):
        beat.preset("nonsense")


# ------------------------------------------------------------- the config

def test_the_response_is_not_called_beat_on_the_config():
    """Every renderer already has a `[beat]` section of its own -- what the
    drums do INSIDE its picture -- and `Config` flattens sections into one
    namespace. Two things named `beat` keep whichever came last."""
    cfg = Config(type="monument")
    assert hasattr(cfg, "response")
    assert cfg.params.beat is not cfg.response


@pytest.mark.parametrize("slug", PRESETS)
def test_a_preset_survives_a_save_and_a_load(slug, tmp_path):
    cfg = Config(type="monument").with_beat(slug)
    cfg.save(tmp_path / "c.toml")
    back = Config.load(tmp_path / "c.toml")
    assert back.beat_preset == slug
    assert back.response.active() == cfg.response.active()


def test_a_hand_edit_survives_a_reload(tmp_path):
    """The preset names it; the sections carry the numbers. Storing only the
    name would snap a tweaked look back to the shipped values on reload."""
    cfg = Config(type="monument").with_beat("punch")
    cfg.response.zoom.amount = 1.21
    cfg.save(tmp_path / "c.toml")
    assert Config.load(tmp_path / "c.toml").response.zoom.amount == 1.21


def test_the_renderers_own_beat_section_is_untouched(tmp_path):
    cfg = Config(type="monument").with_beat("jolt")
    cfg.params.beat.kick_lift = 0.07
    cfg.save(tmp_path / "c.toml")
    assert Config.load(tmp_path / "c.toml").params.beat.kick_lift == 0.07


# -------------------------------------------------------------- the chain

@pytest.mark.parametrize("renderer", RENDERERS)
@pytest.mark.parametrize("slug", PRESETS)
def test_every_preset_builds_against_every_word_look(renderer, slug):
    """The claim the whole design rests on: the chain knows nothing about which
    renderer drew the frame, so all 8 x 5 combinations are one code path."""
    cfg = Config(type=renderer).with_beat(slug)
    specs = compose.network(cfg)
    names = [s.name for s in specs]
    assert "out" in names
    assert "fx_drive" in names
    assert len(names) == len(set(names)), "an operator name is used twice"


def test_the_chain_reaches_the_renderer_by_select_rather_than_a_wire():
    """A TOP inside a base COMP cannot be wired to one outside it, and the
    `wire` tool reports success while leaving the input unconnected."""
    specs = {s.name: s for s in compose.network(Config(type="monument"))}
    assert specs["fx_in"].type == "selectTOP"
    assert specs["fx_in"].params["top"] == "words/out"
    assert not specs["fx_in"].inputs


def test_the_chain_ends_where_render_records():
    """`render` records `/project1/out` unconditionally."""
    specs = {s.name: s for s in compose.network(Config(type="monument"))}
    assert specs["out"].type == "nullTOP"


def test_nothing_may_exceed_white():
    """A Level TOP remaps rather than clamps, so the bloom's lift is held by a
    minimum against a constant. Brightness stacking is the defect this project
    has fixed three times."""
    specs = {s.name: s for s in compose.network(Config(type="monument"))}
    assert specs["fx_clamp"].params["operand"] == "minimum"
    assert specs["out"].inputs == ["fx_clamp"]


def test_the_split_chain_appears_only_when_the_split_is_on():
    """Three TOPs that do nothing are three TOPs cooking every frame."""
    off = {s.name for s in compose.network(Config(type="monument").with_beat("punch"))}
    on = {s.name for s in compose.network(Config(type="monument").with_beat("fracture"))}
    assert "fx_split" not in off
    assert "fx_split" in on and "fx_r" in on and "fx_b" in on


# --------------------------------------------------- the script that drives

@pytest.fixture
def drive():
    """`fx_drive` loaded the way TouchDesigner loads it, prelude and all."""
    src = compose.drive_source()
    mod = pytypes.ModuleType("fx_drive_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "fx_drive.py", "exec"), mod.__dict__)
    return mod


def test_the_script_and_the_module_agree_about_the_shape(drive):
    """`fx_drive` cannot import `beat.py` -- it is pushed as one DAT -- so the
    envelope exists twice. A drift between them would mean the preview and the
    render disagree about the feel, silently."""
    assert drive.ATTACK == beat.ATTACK
    for decay in (0.2, 0.45, 1.0):
        for i in range(60):
            t = 1.0 + i * decay / 30
            assert drive._impulse(t, 1.0, decay) == pytest.approx(
                beat.impulse(t, 1.0, decay), abs=1e-9), (decay, t)


def test_the_script_drifts_the_same_way(drive):
    for t in (0.0, 3.7, 19.2):
        assert drive._drift(t) == pytest.approx(beat.drift(t), abs=1e-9)


def test_the_script_declares_every_number_the_chain_needs(drive):
    """A key in DEFAULTS is a promise the renderer uses the value; a missing one
    means the effect silently runs on a fallback."""
    cfg = Config(type="monument").with_beat("fracture")
    for key in compose.drive_params(cfg):
        assert key in drive.DEFAULTS, f"fx_drive has no default for {key!r}"


def test_the_last_strike_is_found_by_bisection(drive):
    drive.S["drums"] = {"kick": [1.0, 2.0, 3.0], "snare": [], "hat": []}
    assert drive._last("kick", 0.5) < 0
    assert drive._last("kick", 2.5) == 2.0
    assert drive._last("kick", 99.0) == 3.0
    assert drive._last("snare", 5.0) < 0


def test_a_song_with_no_drums_does_not_raise(drive):
    drive.S["drums"] = {"kick": [], "snare": [], "hat": []}
    assert drive._impulse(1.0, drive._last("kick", 1.0), 0.4) == 0.0
