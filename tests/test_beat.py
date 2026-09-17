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


def test_the_script_and_the_module_throw_the_jolt_the_same_way(drive):
    """The third thing that exists twice, for the same reason as the other two."""
    for tilt in (0.0, 0.25, 0.45, 1.0):
        for t in (0.0, 1.3, 7.9, 22.4):
            a = drive._shake_offset(t, 0.8, 40.0, tilt)
            b = beat.shake_offset(t, 0.8, 40.0, tilt)
            assert a == pytest.approx(b, abs=1e-9), (tilt, t)


def test_the_jolt_throws_as_far_as_it_says_it_does():
    """`shake.amount` is a peak displacement, and it has to be that.

    It used to be multiplied by `drift()` itself -- a wander in -1..1 whose
    mean absolute value is 0.39 -- so the direction doubled as the magnitude
    and a jolt asking for 32 pixels landed as about 6, wandering. Jolt read as
    a dimmer Punch because its knock could not be seen at all.
    """
    import math

    for tilt in (0.0, 0.3, 0.45, 0.8, 1.0):
        far = [math.hypot(*beat.shake_offset(t, 1.0, 40.0, tilt))
               for t in (0.0, 0.9, 4.4, 11.1, 26.3)]
        assert far == pytest.approx([40.0] * len(far), rel=1e-6), tilt


def test_the_jolt_is_scaled_by_its_envelope_and_wanders_in_direction():
    import math

    assert beat.shake_offset(3.0, 0.0, 40.0, 0.45) == (0.0, 0.0)
    assert math.hypot(*beat.shake_offset(3.0, 0.5, 40.0, 0.45)) == pytest.approx(20.0)
    # The direction is not the same twice running, or every hit throws the
    # frame the same way and it reads as a repeated cut.
    ways = {tuple(round(v / 40.0, 2) for v in beat.shake_offset(t, 1.0, 40.0, 0.45))
            for t in (0.3, 2.1, 5.8, 9.4, 14.7, 21.2)}
    assert len(ways) > 4, ways


def test_tilt_only_steers_the_jolt(drive):
    """All-horizontal reads as a skip rather than a knock, so tilt exists -- but
    it must not quietly halve the throw, which is what weighting the axes and
    stopping there did."""
    import math

    flat = beat.shake_offset(2.2, 1.0, 40.0, 0.0)
    tall = beat.shake_offset(2.2, 1.0, 40.0, 1.0)
    assert abs(flat[1]) < 1e-9 and abs(tall[0]) < 1e-9
    assert math.hypot(*flat) == pytest.approx(40.0)
    assert math.hypot(*tall) == pytest.approx(40.0)


def test_the_script_declares_every_number_the_chain_needs(drive):
    """A key in DEFAULTS is a promise the renderer uses the value; a missing one
    means the effect silently runs on a fallback."""
    cfg = Config(type="monument").with_beat("fracture")
    for key in compose.drive_params(cfg):
        assert key in drive.DEFAULTS, f"fx_drive has no default for {key!r}"


def test_every_section_of_the_response_reaches_the_driver(drive):
    """The class, not the instance.

    `test_the_script_declares_every_number_the_chain_needs` walks
    `compose.drive_params`, which is a hand-written tuple of section names --
    so a new section that the tuple never learned about passes it. This walks
    the dataclass instead. A section the driver never heard of would report
    success and change nothing, which is this project's commonest defect and
    exactly what adding one invites.
    """
    from dataclasses import fields

    missing = []
    for sec in fields(beat.Response):
        for f in fields(sec.type if not isinstance(sec.type, str)
                        else getattr(beat, sec.type)):
            key = f"{sec.name}_{f.name}"
            if key not in drive.DEFAULTS:
                missing.append(key)
    assert not missing, (
        f"fx_drive has no default for {missing} -- the effect would run on "
        "whatever the fallback happens to be and report success")


def test_every_section_of_the_response_is_pushed(drive):
    """The other half: declared in the driver, and actually written to it."""
    from dataclasses import fields

    pushed = compose.drive_params(Config(type="monument").with_beat("ash"))
    for sec in fields(beat.Response):
        assert any(k.startswith(f"{sec.name}_") for k in pushed), (
            f"nothing from [{sec.name}] is pushed to the driver")


def test_the_last_strike_is_found_by_bisection(drive):
    drive.S["drums"] = {"kick": [1.0, 2.0, 3.0], "snare": [], "hat": []}
    assert drive._last("kick", 0.5) < 0
    assert drive._last("kick", 2.5) == 2.0
    assert drive._last("kick", 99.0) == 3.0
    assert drive._last("snare", 5.0) < 0


def test_a_song_with_no_drums_does_not_raise(drive):
    drive.S["drums"] = {"kick": [], "snare": [], "hat": []}
    assert drive._impulse(1.0, drive._last("kick", 1.0), 0.4) == 0.0


def test_the_driver_reads_the_dat_the_chain_creates(drive):
    """One writer, one reader, one name.

    `fx_drive` read `params` while the chain created and `sync` wrote
    `fx_params`. Nothing failed: a field script that cannot find its DAT falls
    back to the defaults compiled into it and draws a plausible picture, so all
    five preset previews recorded as the same thing -- `jolt` and `pulse`
    identical to three decimal places.

    This is the third time in this project that a name mismatch between a
    writer and a reader has shipped as "it works, but every look is the same".
    """
    from lyricfield import sync

    created = {s.name for s in compose.network(Config(type="monument"))}
    assert drive.PARAMS_DAT in created, (
        f"fx_drive reads {drive.PARAMS_DAT!r}, which the chain does not create; "
        f"it would silently run on its defaults")
    # ... and the writer agrees with both.
    src = __import__("inspect").getsource(sync.push_composed)
    assert f'"{drive.PARAMS_DAT}"' in src


def test_the_driver_reports_when_it_cannot_find_its_params(drive):
    """The flag that would have caught the above. A renderer running on
    fallbacks must say so rather than drawing something plausible."""
    drive.S.clear()
    drive.__dict__["op"] = lambda name: None
    drive._apply_params()
    assert drive.PARAMS_MISSING is True


# ------------------------------------------------------------- the posters

def test_a_poster_is_picked_against_the_unaffected_capture(tmp_path):
    """A tile shows its poster at rest, and for a beat effect any fixed moment
    is the wrong one: a punch lasts one or two frames in ninety-six, so the
    midpoint lands between hits and all five presets show the same still.

    "Furthest from its own average" does not work either -- that finds the
    frame where the WORD changes, which every preset shares. The reference has
    to be the same look with the effect off.
    """
    import numpy as np

    from lyricfield import styles as styles_mod

    # A baseline that never moves, and a clip with one bright frame in it.
    base = np.zeros((10, 8, 6), np.float32)
    shot = base.copy()
    shot[7] = 200.0

    calls: dict = {}
    monkey = {"video": shot, "baseline": base}

    def fake_frames(v, w):
        return monkey["video"] if v == "clip" else monkey["baseline"]

    import subprocess as sp

    from lyricfield import render as render_mod

    def fake_run(argv, **k):
        calls["argv"] = argv
        return sp.CompletedProcess(argv, 0, b"", b"")

    real = (render_mod._gray_frames, styles_mod._fps_of, sp.run)
    render_mod._gray_frames = fake_frames
    styles_mod._fps_of = lambda v: 24.0
    sp.run = fake_run
    try:
        at = styles_mod.poster_against("clip", "base", tmp_path / "p.png")
    finally:
        render_mod._gray_frames, styles_mod._fps_of, sp.run = real

    assert at is not None
    # frame 7 of a 24fps clip
    assert at == pytest.approx(7 / 24.0, abs=1e-6), at
    assert "-ss" in calls["argv"]


def test_a_poster_falls_back_rather_than_raising(tmp_path):
    """A clip too short to compare, or one ffmpeg could not read, must not stop
    a preview that is otherwise fine."""
    from lyricfield import render as render_mod
    from lyricfield import styles as styles_mod

    real = render_mod._gray_frames
    render_mod._gray_frames = lambda v, w: None
    try:
        assert styles_mod.poster_against("a", "b", tmp_path / "p.png") is None
    finally:
        render_mod._gray_frames = real


# ------------------------------------------------- the beat a preview is of

def test_the_beat_preview_holds_one_word_across_the_whole_window():
    """The row shows what the beat does to type, so nothing else may move.

    With the fourteen running words the effect competed with eight transitions
    in four seconds, and the tiles read as "just flashes". One word, held, and
    the only thing left moving is the effect.

    Two cues, not one: `monument._life` holds a word until the NEXT cue lands,
    or for `word.hold` (0.4s) if it is the last, so a lone cue fades out before
    the first kick. The second exists only to be the next one.
    """
    from lyricfield import styles as S
    from lyricfield.cues import CueTable

    starts = sorted(c.start for c in CueTable.load(S.PREVIEW_BEAT_CUES).cues)
    at, seconds = S.BEAT_MOMENT, 4.0
    assert len(starts) >= 2, "one cue alone fades out; there must be a sentinel"
    assert starts[0] < at, (
        f"the word lands at {starts[0]}s, inside the window from {at}s -- its "
        "arrival is then part of what the tile shows")
    assert starts[1] >= at + seconds, (
        f"the second cue at {starts[1]}s falls inside the window, so the word "
        "changes on screen")


def test_enough_kicks_land_while_that_word_is_up():
    """Every preset is driven by the kick now, so the kicks are the whole of
    what a tile has to show. One is not enough to read a rhythm from."""
    from lyricfield import styles as S
    from lyricfield.drums import DrumTable

    at, seconds = S.BEAT_MOMENT, 4.0
    kicks = [t for t in DrumTable.load(S.PREVIEW_DRUMS).times("kick")
             if at <= t < at + seconds]
    assert len(kicks) >= 3, f"only {len(kicks)} kick(s) from {at}s: {kicks}"


def test_the_words_and_the_beat_are_separate_tables():
    """A lyric preview shows running words; a beat preview shows one held. They
    are different questions and a single table cannot answer both -- which is
    what made the beat row unreadable."""
    from lyricfield import styles as S

    assert S.PREVIEW_CUES != S.PREVIEW_BEAT_CUES
    assert S.PREVIEW_BEAT_CUES.exists()


def test_the_placeholder_beat_is_a_table_the_renderer_can_read():
    from lyricfield import styles as S
    from lyricfield.drums import DrumTable

    table = DrumTable.load(S.PREVIEW_DRUMS)
    assert table.problems(9.0) == []
    assert DrumTable.from_dat_text(table.to_dat_text()).hits == table.hits


def test_each_preset_is_one_kind_of_motion():
    """The complaint that prompted this: "just flashes to represent the kick
    hit and not what the beatsync style actually does".

    Every preset carried bloom -- a brightness swell -- so the loudest event in
    all four was light and the row read as one effect at four strengths.
    Measured, the peak-to-trough of the frame's mean brightness came to 18.3,
    18.4, 15.9 and 13.7, against a baseline already doing 11.4 on its own.

    A preset is what it does. Only the one whose name is a glow may be a glow.
    """
    glow, geometry = [], []
    for slug, name, _why, _v in beat.PRESETS:
        if slug == "none":
            continue
        r = beat.preset(slug)
        (glow if r.bloom.on else geometry).append(name)
        assert r.active(), f"{name} does nothing at all"
    assert len(glow) == 1, (
        f"{len(glow)} presets swell the glow ({', '.join(glow)}); brightness is "
        "the one thing they cannot each be, or the row is one effect at "
        "different strengths")
    assert len(geometry) >= 4, geometry


def test_every_preset_answers_the_same_drum():
    """So the row can be read across.

    The shake and the tear used to fire on the snare while the brightest moment
    was the kick, so at the instant the eye is drawn to there was nothing to
    tell the tiles apart. Firing together means that at one moment one tile
    grows, one glows, one jumps and one tears.
    """
    for slug, name, _why, _v in beat.PRESETS:
        r = beat.preset(slug)
        drives = {s.drive for s in (r.zoom, r.bloom, r.shake, r.split, r.burst)
                  if s.on}
        assert drives <= {beat.KICK}, (
            f"{name} answers {', '.join(sorted(drives))}; its signature lands "
            "at a different moment from every other tile's")


def test_no_two_presets_are_the_same_set_of_numbers():
    """Distinct by construction, before any video is recorded."""
    import itertools

    from dataclasses import asdict

    seen = {s: asdict(beat.preset(s)) for s, _, _, _ in beat.PRESETS}
    for a, b in itertools.combinations(sorted(seen), 2):
        assert seen[a] != seen[b], f"{a} and {b} are the same preset"


# ---------------------------------------- the push a Generate-only run makes

def test_a_composed_project_gets_the_beat_pushed_to_it():
    """The Generate button starts a run at the `push` stage, skipping
    provision, so this is the only chance a re-picked preset has to reach
    TouchDesigner. `push_all` writes the renderer's half and nothing else -- so
    picking a different preset and pressing Generate silently kept the old one.

    Worse, `push_all` writes the renderer's params to `/project1/params` while
    a composed project's renderer reads `/project1/words/params`.
    """
    from lyricfield import run as run_mod
    from lyricfield import sync as sync_mod
    from lyricfield.config import Config
    from lyricfield.workspace import Workspace

    called = []

    class Stub:
        def run(self, *a, **k):
            return ""

    import tempfile
    from pathlib import Path

    root = Path(tempfile.mkdtemp())
    ws = Workspace.create("Push Test", root=root, copy_source=False)
    cfg = ws.load_config()
    cfg.with_beat("punch")
    ws.save_config(cfg)

    saved = (sync_mod.is_composed, sync_mod.push_composed, sync_mod.push_all,
             sync_mod.reset_drive_state)
    sync_mod.is_composed = lambda c: True
    sync_mod.push_composed = lambda *a, **k: called.append("composed") or ["ok"]
    sync_mod.push_all = lambda *a, **k: called.append("all") or ["ok"]
    sync_mod.reset_drive_state = lambda *a, **k: called.append("reset")
    from lyricfield import compose as compose_mod
    was_missing = compose_mod.chain_missing
    compose_mod.chain_missing = lambda c, cfg: []
    try:
        ctx = run_mod.Ctx(client=Stub(), name=ws.name)
        ctx.workspace = ws
        run_mod._push(ctx, lambda m: None)
    finally:
        (sync_mod.is_composed, sync_mod.push_composed, sync_mod.push_all,
         sync_mod.reset_drive_state) = saved
        compose_mod.chain_missing = was_missing

    assert "composed" in called, called
    assert "all" not in called, "the renderer's params went to the wrong container"
    assert "reset" in called, (
        "the driver caches its drum table and clears it only on a params-length "
        "change; without a reset the push can change nothing")


def test_a_preset_whose_chain_is_not_built_rebuilds_rather_than_pushes():
    """The chain's SHAPE follows the preset: `fx_r`/`fx_b`/`fx_split` exist
    only when the split is on, so switching to `fracture` cannot work by
    pushing parameters however correct they are."""
    from lyricfield import compose

    on = {s.name for s in compose.network(_cfg_with("fracture"))}
    off = {s.name for s in compose.network(_cfg_with("punch"))}
    assert "fx_split" in on and "fx_split" not in off, (on - off)


def _cfg_with(preset):
    from lyricfield.config import Config

    cfg = Config()
    cfg.with_beat(preset)
    return cfg
