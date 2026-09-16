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
class Response:
    zoom: Zoom = field(default_factory=Zoom)
    bloom: Bloom = field(default_factory=Bloom)
    shake: Shake = field(default_factory=Shake)
    split: Split = field(default_factory=Split)

    def validate(self) -> list[str]:
        out: list[str] = []
        for name, sec in (("zoom", self.zoom), ("bloom", self.bloom),
                          ("shake", self.shake), ("split", self.split)):
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
        if self.bloom.lift > 0.5:
            out.append(
                f"bloom.lift {self.bloom.lift} on top of a word already at its "
                "own peak would clip to white")
        return out

    def active(self) -> list[str]:
        """Which effects are switched on, for the UI and for the log."""
        return [n for n, s in (("zoom", self.zoom), ("bloom", self.bloom),
                               ("shake", self.shake), ("split", self.split))
                if s.on]


RANGES: dict[str, tuple] = {
    "amount": (0.0, 40.0, 0.001),
    "decay": (0.05, 3.0, 0.01),
    "float_": (0.0, 1.0, 0.01),
    "lift": (0.0, 0.5, 0.01),
    "tilt": (0.0, 1.0, 0.01),
    "on": (0, 1, 1),
}


def reconcile(r: "Response") -> None:
    """Settle the relationships `validate()` insists on."""
    for sec in (r.zoom, r.bloom, r.shake, r.split):
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
