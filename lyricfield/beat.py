"""What a drum does to the words.

The beat used to be a picture of its own -- a field, rings, bars -- composited
behind the type. Seven renderers went into that premise before it turned out to
be the wrong one. What is wanted is the beat *in* the text: the type punches on
the kick, its glow swells, it jolts, its channels pull apart.

So there is one chain on the word layer, driven by the drum table, and a preset
is a set of numbers rather than a new renderer. That is what makes every effect
work with every word look automatically: nothing here knows or cares which
renderer drew the frame it is moving.

    words/out -> fx_shake -> fx_zoom -> fx_split -> fx_level -> fx_bloom -> out
                                   ^
                    fx_drive reads `drums` and drives all of it

## Floaty, moving, organic -- which is the envelope, not the structure

A linear `1 - age/decay` is what makes a beat effect read as a meter rather
than as something alive: it jumps to full on the hit and falls at a constant
rate. Three things fix that, and they are the whole difference:

  * **Overshoot and settle.** The response passes its target and comes back,
    the way a struck thing does. `_impulse` below.
  * **Nothing is ever fully still.** A slow drift under everything, from three
    incommensurable sines so it never visibly repeats, at an amplitude well
    under the beat response. A layer that is perfectly static between hits is
    what makes the hits look like stutters.
  * **Attacks are fast and releases are slow**, and neither is linear.

`tests/test_beat.py` asserts all three rather than trusting the comment: a
linear ramp fails every one of them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

KICK, SNARE, HAT = "kick", "snare", "hat"
DRIVES = (KICK, SNARE, HAT)

# How long an attack takes, in seconds. Short, but not zero: a step is a click,
# and at 60fps anything under about two frames is a step.
ATTACK = 0.04

# The light one particle carries, before its kernel spreads it.
#
# Calibrated against recordings, not picked, and it took four of them. What the
# numbers had to answer for, in the order the recordings found it:
#
#   1. The splat kernel multiplied the light by 3.4 and the trail by another
#      1.83, neither normalised. Both are normalised now, so `size` changes how
#      soft a particle is and the trail how long, and neither changes how much
#      light a burst puts on the frame.
#   2. Every particle left on the frame of the hit, so the whole count sat on
#      the lettering at once and the word vanished. See `STAGGER`.
#   3. The buffer was sized from `scriptOp.width`, which is 2x2 until the
#      script writes something -- so the dust was a 2x2 image stretched over
#      the frame. That was most of the slab, and no amount of dimming would
#      have found it.
#
# With those three answered, the arithmetic model said a frame mean of 1.3%.
# Recorded, that was a faint fog: the model is right about the light and says
# nothing about whether it READS. Measured off the capture against the
# unaffected baseline, this value puts the dust across about 20% of the frame
# in the 0.05-0.6 band while the word itself stays at 4% above 0.6 -- "mostly
# dark with bright cores", which is what both references show.
SPARK = 22.0

# How long a burst goes on shedding, as a share of a particle's life.
#
# A burst is not an instant. With every particle leaving on the same frame the
# whole count sits on the lettering at once and the word vanishes under a white
# slab -- which is what the first two recordings did, and no amount of dimming
# fixes it, because the fault is that the light is in one place at one moment
# rather than that there is too much of it. With this, and with a particle dark
# until it is off the letters, the type stays legible through its own burst.
STAGGER = 0.25


def _ease(x: float) -> float:
    """Smoothstep, clamped. The one shape every field script already has."""
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def impulse(t: float, struck: float, decay: float, bounce: float = 0.62) -> float:
    """How far through a strike's response `t` is, 0 at rest.

    A fast eased attack and then a *damped spring* rather than a ramp: the
    value falls, crosses its rest point, swings back and settles. That crossing
    is the whole difference between type that reads as struck and type that
    reads as faded, and it is why this is not `1 - age/decay`.

    `bounce` is how many cycles of swing fit in the release. At 0 it is a plain
    eased decay with no overshoot at all, which is the right answer for an
    effect that must not go negative.

    Clamped at BOTH ends. `age` goes negative whenever a strike sits ahead of
    the playhead, which a seek makes routine, and an unclamped `1 - age/decay`
    is then greater than one and grows without limit. Measured once at 0.86 of
    white across a whole field, with everything else invisible inside it.
    """
    age = t - struck
    decay = max(1e-6, float(decay))
    if age < 0.0 or age > decay:
        return 0.0
    if age < ATTACK:
        return _ease(age / ATTACK)
    x = (age - ATTACK) / max(1e-6, decay - ATTACK)
    # `(1-x)**1.8` is the envelope: slow at first, steep at the end, zero on
    # arrival. The cosine is the swing through rest.
    return ((1.0 - x) ** 1.8) * math.cos(math.pi * 2.0 * max(0.0, bounce) * x)


def drift(t: float, seed: float = 0.0) -> float:
    """A slow wander in -1..1 that never repeats on any useful timescale.

    Three incommensurable periods, so the sum has no short common multiple. It
    is what keeps the layer moving between hits; without it every strike reads
    as a stutter out of a freeze.

    A pure function of the timestamp, so a dropped frame or a seek cannot change
    what is drawn -- the rule CLAUDE.md sets for anything with a choice.
    """
    # Periods of about 5.6, 8.8 and 17 seconds. The first draft ran at 20-70s,
    # which over a four-second preview is a one-way ramp rather than a wander --
    # slow enough to be invisible is the same as not being there. The phase
    # offsets stop all three starting at zero together, which would make the
    # first second of every render a ramp from nothing.
    a = math.sin(t * 1.1300 + 0.7 + seed * 1.7)
    b = math.sin(t * 0.7130 + 2.3 + seed * 3.1)
    c = math.sin(t * 0.3670 + 4.1 + seed * 5.9)
    return (a + b + c) / 3.0


def shake_offset(t: float, env: float, span: float, tilt: float,
                 seed: float = 1.0) -> tuple[float, float]:
    """Where the jolt throws the layer, in pixels.

    Direction and magnitude are separate, and keeping them separate is the
    whole point. The first version multiplied the amplitude by `drift()`
    directly -- a wander in -1..1 whose mean absolute value is 0.39 -- so a
    jolt asking for 32 pixels landed as about 6, at an amplitude that also
    wandered. Jolt read as a dimmer Punch because its knock was invisible.

    Here `drift` only picks the direction, normalised, and `span * env` is the
    distance. `tilt` biases it between the axes: 0 throws the layer sideways,
    1 straight up and down, and all-horizontal reads as a skip rather than a
    knock.
    """
    dx, dy = drift(t, seed), drift(t, seed + 1.0)
    n = math.hypot(dx, dy)
    if n < 1e-9:
        dx, dy, n = 1.0, 0.0, 1.0
    # Tilt shapes the direction; it must not shrink the throw. Weighting the
    # axes and stopping there costs about half the amplitude at tilt 0.45, so
    # the vector is renormalised and `amount` is the peak displacement it says
    # it is rather than some fraction of it.
    wx, wy = (dx / n) * (1.0 - tilt), (dy / n) * tilt
    m = math.hypot(wx, wy)
    if m < 1e-9:
        wx, wy, m = (1.0, 0.0, 1.0) if tilt < 0.5 else (0.0, 1.0, 1.0)
    reach = span * env
    return (reach * wx / m, reach * wy / m)


def _hash(i, k):
    """A repeatable 0..1 per particle index. Whole-array, and not a random
    number: the same burst has to come out the same on every machine and on
    every re-render."""
    import numpy as np

    x = np.sin(i * 12.9898 + k * 78.233) * 43758.5453
    return x - np.floor(x)


def burst_points(count, age, life, reach, rise, swirl, span, seed=0.0):
    """Where a burst's particles have got to, `age` seconds after the strike.

    Returns `(dx, dy, bright)` in pixels from each particle's own emitter, with
    y counting UP -- TouchDesigner's arrays are bottom-up and the splat goes in
    the same way round.

    Nothing integrates: position is a closed form in the age, so a dropped
    frame or a seek draws exactly what a clean playthrough would. That is the
    rule CLAUDE.md sets for anything with a choice, and it is why this is not
    the Particle SOP.

    The shape comes off the two references. Speed is an ease-OUT -- fast off
    the strike, then slowing -- because a spray leaves a struck surface and
    then hangs; `rise` carries it upward the way both clips do; and `swirl`
    bends the paths apart over time, which is what turns a spray of dots into
    the strands they actually show.
    """
    import numpy as np

    life = max(1e-6, float(life))
    count = int(max(0, count))
    if count == 0 or age < 0.0 or age >= life * (1.0 + STAGGER):
        z = np.zeros(0, np.float32)
        return z, z, z

    i = np.arange(count, dtype=np.float64)
    r1, r2, r3 = _hash(i, 1.0 + seed), _hash(i, 2.0 + seed), _hash(i, 3.0 + seed)
    r4 = _hash(i, 4.0 + seed)

    # Not every particle leaves at the instant of the strike. Without this they
    # all sit on the lettering together for the first few frames and the word
    # disappears under a white slab -- which is what the first recording of
    # this did, and no amount of dimming fixes it, because the problem is that
    # the light is in one place at one moment rather than that there is too
    # much of it.
    u = (float(age) / life) - r4 * STAGGER
    live = (u >= 0.0) & (u < 1.0)
    u = np.clip(u, 0.0, 1.0)

    ang = r1 * (math.pi * 2.0)
    far = float(reach) * float(span) * (0.35 + 0.65 * r2)
    # Ease-out: (1 - (1-u)^2) is 0 at the strike, steep immediately after, flat
    # by the end of the life.
    d = far * (1.0 - (1.0 - u) ** 2)

    dx = np.cos(ang) * d
    # Sideways is squashed and the rise is added on top, so the cloud is taller
    # than it is wide -- measured on the GHOSTS clip at 0.20 of the width
    # against 0.22 of the height, on a frame twice as tall as it is wide.
    dy = np.sin(ang) * d * 0.8 + float(rise) * float(reach) * float(span) * (u ** 1.6)

    w = float(swirl) * float(span) * 0.05 * (u ** 1.5)
    dx += w * np.sin(r3 * (math.pi * 2.0) + 3.1 * u)
    dy += w * np.cos(r2 * (math.pi * 2.0) + 2.3 * u)

    # Dark until it is off the letters, so the type stays legible through its
    # own burst: `u^0.45` is nearly zero for the first frames of a particle's
    # life and full by a fifth of the way through.
    bright = ((1.0 - u) ** 1.7) * (0.45 + 0.55 * r3) * (u ** 0.45) * live
    return (dx.astype(np.float32), dy.astype(np.float32),
            bright.astype(np.float32))


def taps(size):
    """The kernel one particle is splatted through, as (dx, dy, weight).

    A single pixel at 360x640 upscales to a hard two-pixel square, which reads
    as noise rather than as dust. The references' particles are soft round dots
    with a faint halo, so a particle is a centre and as much of a ring as
    `size` asks for.
    """
    out = [(0, 0, 1.0)]
    size = float(size)
    if size > 1.0:
        e = min(1.0, size - 1.0)
        out += [(1, 0, e), (-1, 0, e), (0, 1, e), (0, -1, e)]
    if size > 2.0:
        e = min(1.0, size - 2.0) * 0.7
        out += [(1, 1, e), (1, -1, e), (-1, 1, e), (-1, -1, e)]
    return tuple(out)


def major(drums, struck, kind, window=0.06):
    """Whether a hit had another drum land with it -- a "major hit".

    The drum table is kind and time with no strength column, so loudness is not
    available and inventing one would be a lie. What IS available is a real
    musical event: a kick and a snare struck together. Those get the bigger
    burst, which is what gives the row of hits the size variation both
    references show.
    """
    for other, times in (drums or {}).items():
        # Hats do not count. They play continuously -- in the shipped preview
        # table there is one on every kick -- so "a hat landed with it" is true
        # of every hit there is, and every burst came out the bigger size.
        if other == kind or other == HAT:
            continue
        for t in times:
            if abs(t - struck) <= window:
                return True
    return False


@dataclass
class Zoom:
    """The layer scales on the hit and settles back."""

    on: bool = True
    drive: str = KICK
    # Peak scale at the hit. 1.0 is no movement. `validate` caps it at 1.35,
    # past which the words genuinely leave the frame; the shipped presets go
    # to 1.20, because 8% was measurable and not visible.
    amount: float = 1.075
    decay: float = 0.42
    # A slow breath under it, as a share of `amount`'s travel.
    float_: float = 0.25


@dataclass
class Bloom:
    """The glow swells and decays. Never moves the type, so it stays readable
    at any strength -- the one effect that is always safe to turn up."""

    on: bool = True
    drive: str = KICK
    # Extra blur radius in pixels at the peak.
    amount: float = 14.0
    decay: float = 0.55
    # Brightness lift that rides with it.
    lift: float = 0.22


@dataclass
class Shake:
    """The layer jolts off-axis and recovers."""

    on: bool = False
    drive: str = SNARE
    # Peak offset as a share of the frame's smaller side.
    amount: float = 0.012
    decay: float = 0.24
    # How much of the jolt is vertical. All-horizontal reads as a skip.
    tilt: float = 0.45


@dataclass
class Split:
    """Red and blue pull apart and snap back."""

    on: bool = False
    drive: str = SNARE
    # Peak separation as a share of the frame's width.
    amount: float = 0.006
    decay: float = 0.20


@dataclass
class Burst:
    """The lettering sheds on the hit and the dust drifts away.

    The one effect here that needs operators of its own rather than only
    numbers -- a Script TOP that draws the particles and a level that scales
    them into the frame -- and it is still an effect ON the words rather than a
    picture behind them: every particle starts on a glyph's own edge and
    carries that glyph's colour, so it works with every word look for free.

    From two references, both watched rather than read about: GHOSTS' "loose
    you", which gives the texture (thousands of small points, filaments, a
    vertical rise -- measured at a frame mean of 4-8% of white with pixels at
    255), and Pablo Torri's BioCloud study, which gives the behaviour: a solid
    form whose surface sheds a spray of soft dots into the dark, dense at the
    source and thinning outward.
    """

    on: bool = False
    drive: str = KICK
    # Particles per burst, in THOUSANDS -- `RANGES` is keyed by field name and
    # `amount` is shared with the zoom's scale, so a count in the tens of
    # thousands would need a range that makes no sense for the others.
    amount: float = 1.6
    # How long a particle lives.
    decay: float = 0.75
    # How far it gets by then, as a share of the frame's smaller side.
    reach: float = 0.38
    # How much of that is upward. Smoke rises; so does this.
    rise: float = 0.35
    # How far the paths bend apart on the way out. This is what makes strands
    # rather than a uniform spray.
    swirl: float = 0.5
    # The dot, in buffer pixels: 1 is a hard point, 3 a soft one with a halo.
    size: float = 1.6
    # How much bigger a burst is when another drum lands with this one.
    swell: float = 1.6


@dataclass
class Response:
    zoom: Zoom = field(default_factory=Zoom)
    bloom: Bloom = field(default_factory=Bloom)
    shake: Shake = field(default_factory=Shake)
    split: Split = field(default_factory=Split)
    burst: Burst = field(default_factory=Burst)

    def validate(self) -> list[str]:
        out: list[str] = []
        for name, sec in (("zoom", self.zoom), ("bloom", self.bloom),
                          ("shake", self.shake), ("split", self.split),
                          ("burst", self.burst)):
            if sec.drive not in DRIVES:
                out.append(f"{name}.drive {sec.drive!r} is not one of "
                           f"{', '.join(DRIVES)}")
            if sec.decay <= 0:
                out.append(f"{name}.decay must be positive; it is a fall time")
            if sec.decay <= ATTACK:
                out.append(
                    f"{name}.decay {sec.decay} is shorter than the {ATTACK}s "
                    f"attack, so the effect would never finish rising")
        if self.zoom.amount < 1.0:
            out.append(
                f"zoom.amount {self.zoom.amount} would shrink the words on a "
                "hit, which reads as a glitch rather than as a punch")
        if self.zoom.amount > 1.35:
            out.append(
                f"zoom.amount {self.zoom.amount} pushes the words past the "
                "edge of the frame")
        if self.shake.amount < 0 or self.split.amount < 0:
            out.append("an offset cannot be negative; it is a distance")
        if not (0.0 <= self.shake.tilt <= 1.0):
            out.append(f"shake.tilt {self.shake.tilt} must be between 0 and 1")
        if self.bloom.amount < 0:
            out.append("bloom.amount is a blur radius and cannot be negative")
        # Brightness stacks at the output, which this project has been bitten by
        # three times. The bloom's lift is the only term here that adds light.
        b = self.burst
        if b.amount < 0:
            out.append("burst.amount is a count of particles, in thousands")
        if b.amount > 40:
            out.append(
                f"burst.amount {b.amount} is {b.amount * 1000:.0f} particles a "
                "burst, which is a cook time rather than a look")
        if b.reach < 0 or b.swirl < 0:
            out.append("burst.reach and burst.swirl are distances")
        if not (0.0 <= b.rise <= 2.0):
            out.append(f"burst.rise {b.rise} is a share of the reach, 0 to 2")
        if b.size < 0.5:
            out.append(
                f"burst.size {b.size} is smaller than the one pixel a particle "
                "is drawn into, so it would draw nothing")
        if b.swell < 1.0:
            out.append(
                f"burst.swell {b.swell} would make a hit with another drum on "
                "it SMALLER than one on its own")
        if self.bloom.lift > 0.5:
            out.append(
                f"bloom.lift {self.bloom.lift} on top of a word already at its "
                "own peak would clip to white")
        return out

    def active(self) -> list[str]:
        """Which effects are switched on, for the UI and for the log."""
        return [n for n, s in (("zoom", self.zoom), ("bloom", self.bloom),
                               ("shake", self.shake), ("split", self.split),
                               ("burst", self.burst))
                if s.on]


RANGES: dict[str, tuple] = {
    "amount": (0.0, 40.0, 0.001),
    "decay": (0.05, 3.0, 0.01),
    "float_": (0.0, 1.0, 0.01),
    "lift": (0.0, 0.5, 0.01),
    "tilt": (0.0, 1.0, 0.01),
    "on": (0, 1, 1),
    "reach": (0.0, 1.0, 0.005), "rise": (0.0, 2.0, 0.01),
    "swirl": (0.0, 3.0, 0.01), "size": (0.5, 4.0, 0.1),
    "swell": (1.0, 3.0, 0.05),
}


def reconcile(r: "Response") -> None:
    """Settle the relationships `validate()` insists on."""
    for sec in (r.zoom, r.bloom, r.shake, r.split, r.burst):
        if sec.drive not in DRIVES:
            sec.drive = KICK
        sec.decay = max(ATTACK + 0.01, float(sec.decay))
    r.zoom.amount = min(1.35, max(1.0, r.zoom.amount))
    r.zoom.float_ = min(1.0, max(0.0, r.zoom.float_))
    r.shake.amount = max(0.0, r.shake.amount)
    r.shake.tilt = min(1.0, max(0.0, r.shake.tilt))
    r.split.amount = max(0.0, r.split.amount)
    r.bloom.amount = max(0.0, r.bloom.amount)
    r.bloom.lift = min(0.5, max(0.0, r.bloom.lift))
    r.burst.amount = min(40.0, max(0.0, r.burst.amount))
    r.burst.reach = max(0.0, r.burst.reach)
    r.burst.rise = min(2.0, max(0.0, r.burst.rise))
    r.burst.swirl = max(0.0, r.burst.swirl)
    r.burst.size = min(4.0, max(0.5, r.burst.size))
    r.burst.swell = min(3.0, max(1.0, r.burst.swell))


# ------------------------------------------------------------------ presets

# The word look the presets are demonstrated on, and where those captures live.
# One word filling the frame: a zoom, a jolt and a channel split all read
# clearly at that size and are nearly invisible on a field of small glyphs.
# Named here rather than in the seeder so the recorder and the server cannot
# disagree about the path.
REFERENCE = "monument"
PREVIEW_DIR = "_beat"


def reference_params(video_type):
    """The reference renderer's own params, with its beat response switched off.

    A preset preview shows what the EFFECT does, so the look it is demonstrated
    on must do nothing on the beat itself. `monument` adds `kick_lift` to the
    ground across the whole frame on every kick, which is its own response and
    is identical in all five tiles -- measured, the `none` tile, which shows no
    effect at all, went from a frame mean of 7.6 to 16.1 on every kick, and it
    was the loudest thing in every tile. The complaint was that the previews
    "show just flashes to represent the kick hit and not what the beatsync
    style actually does", and this was most of why.

    Zeroing `beat.kick_lift` makes monument completely inert: it is that
    renderer's only drum path. Any future reference has to be checked the same
    way, which `tests/test_styles_gallery` does by measuring the baseline.
    """
    p = video_type.default_params()
    sec = getattr(p, "beat", None)
    if sec is not None:
        for name in ("kick_lift", "snare_lift", "hat_lift", "kick_push",
                     "hat_grain"):
            if hasattr(sec, name):
                setattr(sec, name, 0.0)
    return p


def preview_url(slug: str) -> str:
    return f"/styles/{PREVIEW_DIR}/{REFERENCE}/{slug}/preview.mp4"

# What ships in the second row. A preset is numbers, so adding one costs a dict
# and works with every word renderer without being told about any of them.
#
# ONE KIND OF MOTION EACH, AND ALL OF IT ON THE KICK. Both halves of that were
# learned by getting them wrong. Every preset used to carry bloom -- a
# brightness swell -- so the loudest event in all four was light, and the row
# read as one effect at four strengths: measured, the peak-to-trough of the
# frame's mean brightness was 18.3, 18.4, 15.9, 13.7 against a baseline that
# was itself doing 11.4. And the two effects that would have told them apart,
# the shake and the tear, fired on the SNARE while the brightest moment was the
# kick, so at the instant the eye is drawn to there was nothing to see but the
# glow. Now: Punch is size, Pulse is light, Jolt is position, Fracture is
# colour, and they all happen at the same moment so the row can be read across.
PRESETS: tuple[tuple[str, str, str, dict], ...] = (
    ("none", "None",
     "the words are left alone",
     {"zoom.on": False, "bloom.on": False, "shake.on": False,
      "split.on": False}),

    ("punch", "Punch",
     "the type swells hard on every kick and settles back",
     {"zoom.on": True, "zoom.drive": KICK, "zoom.amount": 1.26,
      "zoom.decay": 0.40,
      "bloom.on": False, "shake.on": False, "split.on": False}),

    ("pulse", "Pulse",
     "the glow breathes wide with the kick; the words never move",
     {"zoom.on": False,
      "bloom.on": True, "bloom.drive": KICK, "bloom.amount": 46.0,
      "bloom.lift": 0.42, "bloom.decay": 0.75,
      "shake.on": False, "split.on": False}),

    ("jolt", "Jolt",
     "a hard knock that throws the words off their line",
     {"zoom.on": False, "bloom.on": False,
      "shake.on": True, "shake.drive": KICK, "shake.amount": 0.060,
      "shake.decay": 0.26, "shake.tilt": 0.45,
      "split.on": False}),

    ("ash", "Ash",
     "the letters shed on every kick and the dust drifts away",
     {"zoom.on": False, "bloom.on": False, "shake.on": False,
      "split.on": False,
      "burst.on": True, "burst.drive": KICK, "burst.amount": 1.6,
      "burst.decay": 0.75, "burst.reach": 0.38, "burst.rise": 0.35,
      "burst.swirl": 0.5, "burst.size": 1.6, "burst.swell": 1.6}),

    ("fracture", "Fracture",
     "the colour channels tear apart and snap back",
     {"zoom.on": False, "bloom.on": False,
      "shake.on": True, "shake.drive": KICK, "shake.amount": 0.014,
      "shake.decay": 0.20, "shake.tilt": 0.25,
      "split.on": True, "split.drive": KICK, "split.amount": 0.065,
      "split.decay": 0.28}),
)


def preset(slug: str) -> Response:
    """A fresh `Response` wearing the named preset."""
    for name, _label, _why, values in PRESETS:
        if name == slug:
            r = Response()
            for path, v in values.items():
                sec, key = path.split(".")
                setattr(getattr(r, sec), key, v)
            reconcile(r)
            return r
    raise KeyError(f"no beat preset {slug!r} "
                   f"(known: {', '.join(p[0] for p in PRESETS)})")


def preset_payload() -> list[dict]:
    """The presets as the gallery needs them."""
    return [{"slug": s, "name": n, "description": d} for s, n, d, _ in PRESETS]
