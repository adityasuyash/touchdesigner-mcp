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


@dataclass
class Zoom:
    """The layer scales on the hit and settles back."""

    on: bool = True
    drive: str = KICK
    # Peak scale. 1.0 is no movement; much past 1.2 and the words leave frame.
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

# What ships in the second row. A preset is numbers, so adding one costs a dict
# and works with every word renderer without being told about any of them.
PRESETS: tuple[tuple[str, str, dict], ...] = (
    ("none", "None",
     "the words are left alone",
     {"zoom.on": False, "bloom.on": False, "shake.on": False,
      "split.on": False}),

    ("punch", "Punch",
     "the type swells on every kick and settles back",
     {"zoom.on": True, "zoom.drive": KICK, "zoom.amount": 1.085,
      "zoom.decay": 0.40,
      "bloom.on": True, "bloom.drive": KICK, "bloom.amount": 10.0,
      "bloom.lift": 0.14, "bloom.decay": 0.45,
      "shake.on": False, "split.on": False}),

    ("pulse", "Pulse",
     "the glow breathes with the kick; the words never move",
     {"zoom.on": False,
      "bloom.on": True, "bloom.drive": KICK, "bloom.amount": 24.0,
      "bloom.lift": 0.3, "bloom.decay": 0.7,
      "shake.on": False, "split.on": False}),

    ("jolt", "Jolt",
     "a hard knock on the snare over a kick-driven swell",
     {"zoom.on": True, "zoom.drive": KICK, "zoom.amount": 1.06,
      "zoom.decay": 0.3,
      "bloom.on": True, "bloom.drive": KICK, "bloom.amount": 8.0,
      "bloom.lift": 0.1, "bloom.decay": 0.3,
      "shake.on": True, "shake.drive": SNARE, "shake.amount": 0.018,
      "shake.decay": 0.22, "shake.tilt": 0.5,
      "split.on": False}),

    ("fracture", "Fracture",
     "the channels tear apart on the snare and the frame kicks",
     {"zoom.on": False,
      "bloom.on": True, "bloom.drive": KICK, "bloom.amount": 6.0,
      "bloom.lift": 0.08, "bloom.decay": 0.25,
      "shake.on": True, "shake.drive": KICK, "shake.amount": 0.009,
      "shake.decay": 0.18, "shake.tilt": 0.2,
      "split.on": True, "split.drive": SNARE, "split.amount": 0.009,
      "split.decay": 0.22}),
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
