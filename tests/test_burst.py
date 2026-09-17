"""Ash: the lettering sheds on the hit and the dust drifts away.

The one beat effect with a picture of its own, and therefore the one that can
fail silently in ways the other four cannot -- a Script TOP that draws black
reports nothing at all. So these tests draw frames and measure them.

Both references were watched rather than read about. GHOSTS' "loose you" gives
the texture: sampled at 180x320 over 326 frames, a mean of 4-8% of white with
individual pixels at 255, a mass 0.20 of the width and 0.22 of the height.
Pablo Torri's BioCloud study gives the behaviour: a solid form whose SURFACE
sheds a spray of soft dots into the dark, dense at the source and thinning
outward.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import beat
from lyricfield import compose
from lyricfield.config import Config


@pytest.fixture
def drive():
    """`fx_drive` loaded the way TouchDesigner loads it, prelude and all."""
    src = compose.drive_source()
    mod = pytypes.ModuleType("fx_drive_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "fx_drive.py", "exec"), mod.__dict__)
    return mod


class FakeTOP:
    """A Script TOP's half of the contract: an input to read and a frame to
    write back.

    Deliberately NOT a source of the buffer size. A Script TOP's resolution is
    whatever its script last wrote, so `scriptOp.width` answers 2x2 on the
    first cook and the script that trusts it stays there -- which is exactly
    what the first recording of this did.
    """

    def __init__(self, w=None, h=None, src=None, name="fx_burst"):
        self.width, self.height, self.name = w, h, name
        self.inputs = [_Src(src)] if src is not None else []
        self.written = None

    def copyNumpyArray(self, a):
        self.written = np.array(a)


class _Src:
    def __init__(self, a):
        self._a = a

    def numpyArray(self, delayed=False):
        return self._a


def _type_frame(w=180, h=320, colour=(1.0, 1.0, 1.0)):
    """A block of white type on black, bottom-up the way TouchDesigner's
    arrays are."""
    a = np.zeros((h, w, 4), np.float32)
    a[h // 2 - 20:h // 2 + 20, w // 2 - 40:w // 2 + 40, :3] = colour
    a[:, :, 3] = 1.0
    return a


def _burst_on(drive, **over):
    drive.WIDTH, drive.HEIGHT = 720, 1280
    drive.BURST_ON = True
    for k, v in dict(BURST_DRIVE="kick", BURST_AMOUNT=2.0, BURST_DECAY=0.9,
                     BURST_REACH=0.22, BURST_RISE=0.35, BURST_SWIRL=0.5,
                     BURST_SIZE=1.6, BURST_SWELL=1.6).items():
        setattr(drive, k, over.get(k[6:].lower(), v))
    for k, v in over.items():
        setattr(drive, "BURST_" + k.upper(), v)
    drive.S.clear()
    drive.S["drums"] = {"kick": [1.0], "snare": [], "hat": []}


# ------------------------------------------------- the script and the module

def test_the_script_and_the_module_place_the_particles_alike(drive):
    """`fx_drive` cannot import `beat.py` -- it is pushed as one DAT -- so the
    maths exists twice, and the same test that keeps the envelopes in step
    keeps these in step. A drift means the preview and the render disagree."""
    for age in (0.0, 0.05, 0.3, 0.89):
        a = beat.burst_points(64, age, 0.9, 0.22, 0.35, 0.5, 640.0)
        b = drive._burst_points(64, age, 0.9, 0.22, 0.35, 0.5, 640.0)
        for x, y in zip(a, b):
            assert x == pytest.approx(y, abs=1e-9), age


def test_the_script_and_the_module_agree_on_the_kernel_and_the_major_hit(drive):
    for size in (0.5, 1.0, 1.6, 2.4, 4.0):
        assert drive._taps(size) == beat.taps(size)
    drums = {"kick": [1.0], "snare": [1.03], "hat": []}
    assert drive._major(drums, 1.0, "kick") == beat.major(drums, 1.0, "kick")
    assert not beat.major({"kick": [1.0], "snare": [2.0]}, 1.0, "kick")


# ------------------------------------------------------------- the particles

def test_a_particle_is_a_pure_function_of_its_age():
    """No integration anywhere, so a dropped frame or a seek draws exactly what
    a clean playthrough draws. The rule CLAUDE.md sets, and the reason this is
    not the Particle SOP."""
    one = beat.burst_points(200, 0.4, 0.9, 0.22, 0.35, 0.5, 640.0)
    two = beat.burst_points(200, 0.4, 0.9, 0.22, 0.35, 0.5, 640.0)
    for a, b in zip(one, two):
        assert np.array_equal(a, b)


def test_nothing_is_drawn_before_the_strike_or_after_the_life():
    """Clamped at BOTH ends. An age goes negative whenever a strike sits ahead
    of the playhead, which a seek makes routine. The far end is the life plus
    the stagger, since the last particle to leave still has a full life."""
    gone = 0.9 * (1.0 + beat.STAGGER) + 1e-6
    for age in (-2.0, -0.01, gone, 5.0):
        dx, dy, br = beat.burst_points(100, age, 0.9, 0.22, 0.35, 0.5, 640.0)
        assert dx.size == dy.size == br.size == 0, age


def test_a_particle_stays_inside_the_reach_it_was_given():
    dx, dy, _b = beat.burst_points(2000, 0.85, 0.9, 0.22, 0.0, 0.0, 640.0)
    far = np.hypot(dx, dy).max()
    assert far <= 0.22 * 640.0 * 1.01, far
    assert far > 0.22 * 640.0 * 0.6, "nothing got anywhere near the reach"


def test_the_dust_rises():
    """Smoke rises, and so does this -- it is the strongest thing both
    references have in common."""
    _dx, dy, _b = beat.burst_points(4000, 0.8, 0.9, 0.22, 0.8, 0.0, 640.0)
    assert dy.mean() > 0.0, "the cloud sank"
    flat = beat.burst_points(4000, 0.8, 0.9, 0.22, 0.0, 0.0, 640.0)[1]
    assert abs(flat.mean()) < abs(dy.mean()) * 0.4


def test_a_burst_swells_and_then_fades_rather_than_being_cut():
    """It is dark on the frame of the hit -- every particle is still on the
    lettering then -- swells as the dust gets clear of the letters, and fades
    out. A burst that started at full brightness buried the word."""
    seen = [float(beat.burst_points(400, a, 0.9, 0.22, 0.35, 0.5, 640.0)[2].sum())
            for a in (0.02, 0.12, 0.3, 0.6, 0.95, 1.1)]
    top = seen.index(max(seen))
    assert 0 < top <= 2, f"peaked at sample {top}: {seen}"
    assert seen[0] < max(seen) * 0.2, f"it arrived at full brightness: {seen}"
    assert seen[-1] < max(seen) * 0.1, f"it never left: {seen}"


def test_speed_eases_OUT_rather_than_being_constant():
    """A spray leaves a struck surface fast and then hangs. Constant speed is
    what an emitter does, not what a hit does."""
    # One cohort, all born on the hit -- with the stagger in, the mean mixes
    # particles at different ages and says nothing about any of them. Equal
    # steps too, or the comparison is of intervals rather than of speed.
    was, beat.STAGGER = beat.STAGGER, 0.0
    try:
        far = [np.hypot(*beat.burst_points(300, a, 0.9, 0.22, 0.0, 0.0,
                                           640.0)[:2]).mean()
               for a in (0.0, 0.2, 0.4, 0.6)]
    finally:
        beat.STAGGER = was
    steps = [b - a for a, b in zip(far, far[1:])]
    assert steps == sorted(steps, reverse=True), steps


# ------------------------------------------------------------- the emitters

def test_the_particles_leave_the_TYPE_and_not_a_box(drive):
    """"The beatsync is just an additive effect on any text style we choose",
    visible in the text itself. Every particle starts on a glyph."""
    _burst_on(drive)
    src = _type_frame()
    top = FakeTOP(src=src)
    seeded = drive._emitters(top, 1.0, 500)
    assert seeded is not None
    ex, ey, _col = seeded
    h, w = src.shape[:2]
    lit = src[:, :, 0] > 0.35
    on_type = lit[np.clip((ey * h).astype(int), 0, h - 1),
                  np.clip((ex * w).astype(int), 0, w - 1)]
    assert on_type.mean() > 0.98, f"only {on_type.mean():.2%} started on the type"


def test_the_particles_leave_the_EDGE_of_the_type(drive):
    """The BioCloud reference sheds from a SURFACE, not out of a solid. On a
    block of type, that means the boundary rows and columns."""
    _burst_on(drive)
    src = _type_frame()
    seeded = drive._emitters(FakeTOP(src=src), 1.0, 800)
    ex, ey, _col = seeded
    h, w = src.shape[:2]
    lit = src[:, :, 0] > 0.35
    inner = np.zeros_like(lit)
    inner[1:-1, 1:-1] = (lit[1:-1, 1:-1] & lit[:-2, 1:-1] & lit[2:, 1:-1]
                         & lit[1:-1, :-2] & lit[1:-1, 2:])
    on_edge = (lit & ~inner)[np.clip((ey * h).astype(int), 0, h - 1),
                             np.clip((ex * w).astype(int), 0, w - 1)]
    assert on_edge.mean() > 0.98, (
        f"only {on_edge.mean():.2%} started on an edge; the burst is coming "
        "out of the middle of the letters")


def test_the_dust_carries_the_type_own_colour(drive):
    """So a blue-inked look throws blue dust, and nothing in the chain has to
    know which renderer drew the frame."""
    _burst_on(drive)
    blue = _type_frame(colour=(0.1, 0.2, 1.0))
    _ex, _ey, col = drive._emitters(FakeTOP(src=blue), 1.0, 200)
    assert col[2] == pytest.approx(1.0, abs=1e-5)
    assert col[0] < 0.2 and col[1] < 0.3, col


def test_the_emitters_are_the_same_every_time_for_one_strike(drive):
    _burst_on(drive)
    src = _type_frame()
    one = drive._emitters(FakeTOP(src=src), 1.0, 300)
    two = drive._emitters(FakeTOP(src=src), 1.0, 300)
    for a, b in zip(one, two):
        assert np.array_equal(a, b)
    other = drive._emitters(FakeTOP(src=src), 2.5, 300)
    assert not np.array_equal(one[0], other[0]), "two strikes drew one burst"


def test_the_buffer_is_sized_from_the_pushed_frame_not_from_the_operator(drive):
    """A Script TOP's resolution is what its script last wrote. Asking the
    operator how big it is answers 2x2 on the first cook and a script that
    believes it writes 2x2 for ever -- which, stretched over the frame, is one
    enormous soft blob where the dust should be. Recorded exactly that way
    once."""
    _burst_on(drive)
    top = FakeTOP(2, 2, _type_frame())        # what TouchDesigner says
    drive._draw_burst(top, 1.2)
    assert top.written.shape == (1280 // 2, 720 // 2, 4), top.written.shape


def test_a_frame_with_no_type_in_it_draws_nothing_and_does_not_raise(drive):
    _burst_on(drive)
    dark = np.zeros((320, 180, 4), np.float32)
    assert drive._emitters(FakeTOP(src=dark), 1.0, 100) is None
    top = FakeTOP(src=dark)
    assert drive._draw_burst(top, 1.1) == 0
    assert float(top.written[:, :, :3].max()) == 0.0


# ----------------------------------------------------------------- the frame

def test_the_dust_lands_OUTSIDE_the_lettering(drive):
    """The check a brightness measurement cannot make. A frame that merely got
    brighter passes every mean-and-peak test ever written here; what says the
    particles are real is light where the type is NOT."""
    _burst_on(drive)
    src = _type_frame()
    top = FakeTOP(src=src)
    drive._draw_burst(top, 1.0 + 0.45)
    frame = top.written[:, :, 0]

    h, w = frame.shape
    lit = np.zeros((h, w), bool)
    lit[h // 2 - 40:h // 2 + 40, w // 2 - 80:w // 2 + 80] = True   # the type, scaled
    outside = float(frame[~lit].sum())
    assert outside > 0.0, "every particle is still on the lettering"
    assert outside > float(frame.sum()) * 0.25, (
        f"only {outside / max(1e-9, frame.sum()):.0%} of the light left the type")


def test_the_burst_spikes_on_the_hit_and_is_gone_before_the_next(drive):
    """What "reacts on every kick" has to mean, measured rather than eyeballed."""
    _burst_on(drive, decay=0.6)
    drive.S["drums"] = {"kick": [1.0, 3.0], "snare": [], "hat": []}
    src = _type_frame()
    light = {}
    for t in (0.9, 1.05, 1.3, 1.5, 1.8, 2.9):
        top = FakeTOP(src=src)
        drive._draw_burst(top, t)
        light[t] = float(top.written[:, :, :3].sum())
    assert light[0.9] == 0.0, "the dust was there before the kick"
    assert light[1.05] > 0.0, "nothing at all on the hit"
    assert light[1.3] > light[1.05], f"it did not swell: {light}"
    assert light[1.3] > light[1.5] > 0.0, light
    assert light[1.8] == 0.0 and light[2.9] == 0.0, (
        f"still lit a whole life and a stagger after the hit: {light}")


def test_a_hit_with_another_drum_on_it_bursts_bigger(drive):
    """A "major hit" is derived rather than invented: the drum table is kind
    and time with no strength column, so loudness is not available -- but a
    kick and a snare struck together is a real musical event."""
    src = _type_frame()
    _burst_on(drive)
    alone = FakeTOP(src=src)
    drive._draw_burst(alone, 1.2)

    _burst_on(drive)
    drive.S["drums"] = {"kick": [1.0], "snare": [1.02], "hat": []}
    together = FakeTOP(src=src)
    drive._draw_burst(together, 1.2)

    # RGB only: the alpha channel is 1.0 across a quarter of a million pixels
    # and swamps the thing being measured.
    assert (float(together.written[:, :, :3].sum())
            > float(alone.written[:, :, :3].sum()) * 1.2)


def test_the_frame_is_the_same_twice_and_after_a_seek(drive):
    """A render has to come out the same way twice. Drawn at 1.4s directly,
    and at 1.4s after the playhead has been somewhere else entirely."""
    src = _type_frame()
    _burst_on(drive)
    a = FakeTOP(src=src)
    drive._draw_burst(a, 1.4)

    _burst_on(drive)
    for t in (1.05, 1.2, 1.4):
        b = FakeTOP(src=src)
        drive._draw_burst(b, t)
    assert np.array_equal(a.written, b.written)

    _burst_on(drive)
    for t in (7.0, 0.2, 1.4):           # a scrub, forward and back
        c = FakeTOP(src=src)
        drive._draw_burst(c, t)
    assert np.array_equal(a.written, c.written)


def test_switched_off_it_draws_black_and_costs_nothing(drive):
    _burst_on(drive)
    drive.BURST_ON = False
    top = FakeTOP(src=_type_frame())
    assert drive._draw_burst(top, 1.3) == 0
    assert float(top.written[:, :, :3].max()) == 0.0
    assert float(top.written[:, :, 3].min()) == 1.0


def test_the_dust_is_mostly_dark_with_bright_cores(drive):
    """Measured on the GHOSTS clip: a frame mean of 4-8% of white with
    individual pixels at 255. A cloud that fills its frame evenly is fog."""
    _burst_on(drive)
    top = FakeTOP(src=_type_frame())
    drive._draw_burst(top, 1.25)
    f = top.written[:, :, 0]
    lit = f > 0.02
    assert lit.mean() < 0.25, f"{lit.mean():.0%} of the frame is lit; that is fog"
    assert f.max() > f[lit].mean() * 2.0, "no cores, just a haze"


# -------------------------------------------------------------- the network

def test_the_chain_carries_the_burst_whatever_the_preset_is():
    """Always created, however it is switched. A chain whose shape follows the
    preset is a chain `verify` has to reason about -- and switching to a preset
    that needs an operator which is not there can never work by pushing
    parameters, however correct they are."""
    for slug, _n, _w, _v in beat.PRESETS:
        names = {s.name for s in compose.network(Config(type="monument")
                                                .with_beat(slug))}
        assert {"fx_seed", "fx_burst", "fx_sparks", "fx_spark_add"} <= names, slug


def test_the_burst_reads_the_type_and_reaches_the_output():
    """Wired at both ends. A Script TOP with no outputs is in nobody's cook
    chain and TouchDesigner never runs it -- which is exactly how the whole
    beat response was absent from every render for three versions."""
    specs = {s.name: s for s in
             compose.network(Config(type="monument").with_beat("ash"))}
    assert specs["fx_burst"].inputs == ["fx_seed"]
    assert specs["fx_sparks"].inputs == ["fx_burst"]
    assert "fx_sparks" in specs["fx_spark_add"].inputs
    # ... and through the bloom, so the dust glows with the type.
    assert specs["fx_bloom"].inputs == ["fx_spark_add"]
    assert "fx_spark_add" in specs["fx_add"].inputs


def test_the_burst_shares_the_driver_one_callbacks_dat():
    """One DAT, two Script TOPs, told apart by `scriptOp.name`. A second pushed
    script is a second thing that can be stale or never written, and a Script
    TOP with empty callbacks draws black and reports nothing. Confirmed in
    TouchDesigner before it was built this way."""
    specs = {s.name: s for s in
             compose.network(Config(type="monument").with_beat("ash"))}
    assert (specs["fx_burst"].params["callbacks"]
            == specs["fx_drive"].params["callbacks"] == "fx_drive_callbacks")


def test_the_burst_top_is_named_the_way_the_script_expects(drive):
    """The branch is on the operator's NAME, so the two have to agree. They are
    in different files and nothing else would notice."""
    specs = {s.name for s in
             compose.network(Config(type="monument").with_beat("ash"))}
    assert drive.BURST_TOP in specs


def test_the_seed_tap_is_small_enough_to_read_back_cheaply():
    """Measured in TouchDesigner: a numpyArray readback costs 2.03ms a frame at
    720x1280 and 0.17ms at 180x320. The emitters are jittered inside their cell
    anyway, so the resolution buys nothing."""
    cfg = Config(type="monument").with_beat("ash")
    specs = {s.name: s for s in compose.network(cfg)}
    seed = specs["fx_seed"].params
    assert seed["resolutionw"] * seed["resolutionh"] <= 180 * 320
    burst = specs["fx_burst"].params
    assert burst["format"] == "rgba32float"
    assert burst["resolutionw"] == cfg.params.stage.width // 2
