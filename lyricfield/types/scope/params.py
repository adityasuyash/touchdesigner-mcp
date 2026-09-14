"""Scope's tunables: one continuous curve with a phosphor trail.

Reads as an instrument rather than a picture, which is what makes it the third
beat renderer worth having: `rings` is soft and radial, `strata` is hard and
stacked, this is a single glowing line on black and nothing else.

The trail is drawn from the curve's own recent past rather than accumulated in
a buffer, so a frame depends on nothing but its own timestamp -- no feedback,
no carried state, identical on a re-render from any starting point.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .._controls import Control, bind_controls


@dataclass
class Frame:
    width: int = 720
    height: int = 1280
    scale: float = 0.6


@dataclass
class Curve:
    """A Lissajous figure: two sines at a ratio, one per axis."""

    freqx: float = 3.0
    freqy: float = 2.0
    # Slowly slides the two out of phase, so the figure turns through itself
    # instead of repeating the same closed shape forever.
    slip: float = 0.05
    size: float = 0.38       # against the frame's smaller side
    rate: float = 0.9        # how fast the point travels the figure


@dataclass
class Trail:
    """How much of the curve's recent past is still glowing."""

    seconds: float = 0.55
    samples: int = 1400      # points drawn along that past
    weight: float = 0.9      # brightness of the freshest point
    taper: float = 2.6       # how quickly the trail dims behind it


@dataclass
class Look:
    hue: float = 0.33
    sat: float = 0.7
    floor: float = 0.012
    # Generous: a bare line needs the bloom to read as phosphor rather than as
    # a hairline scratch.
    glow: float = 0.55
    bloom: float = 20.0


@dataclass
class Beat:
    # A kick nudges the vertical frequency, so the figure changes shape on the
    # beat rather than merely brightening.
    kick_bend: float = 0.35
    kick_time: float = 0.45
    hat_lift: float = 0.25
    hat_time: float = 0.12
    intro_open: float = 0.3
    arrive: float = 0.85
    outro: float = 12.0


@dataclass
class Params:
    frame: Frame = field(default_factory=Frame)
    curve: Curve = field(default_factory=Curve)
    trail: Trail = field(default_factory=Trail)
    look: Look = field(default_factory=Look)
    beat: Beat = field(default_factory=Beat)

    def validate(self) -> list[str]:
        out: list[str] = []
        f, c, tr, lk, b = (self.frame, self.curve, self.trail, self.look,
                           self.beat)
        if not (0.1 <= f.scale <= 1.0):
            out.append(f"scale {f.scale} must be between 0.1 and 1")
        if c.freqx <= 0 or c.freqy <= 0:
            out.append("freqx and freqy must both be positive")
        if abs(c.freqx - c.freqy) < 1e-6:
            out.append(
                f"freqx and freqy are both {c.freqx}; equal frequencies draw a "
                "line, not a figure")
        if not (0.02 < c.size <= 0.9):
            out.append(f"size {c.size} would put the figure off the frame")
        if tr.seconds <= 0:
            out.append("seconds must be positive; it is the length of the trail")
        if tr.samples < 8:
            out.append(
                f"samples {tr.samples} is too few to draw a line; the trail "
                "would come out as loose dots")
        if lk.floor >= tr.weight:
            out.append("floor must be below the trail's own weight")
        if b.outro <= 0:
            out.append("outro must be positive; it is the length of the ending")
        if not (0.0 < b.intro_open <= 1.0):
            out.append(f"intro_open {b.intro_open} must be above 0 and at most 1")
        if not (0.0 < b.arrive <= 1.0):
            out.append(f"arrive {b.arrive} must be above 0 and at most 1")
        return out


RANGES: dict[str, tuple] = {
    "width": (240, 2160, 2), "height": (240, 3840, 2),
    "scale": (0.1, 1.0, 0.05),
    "freqx": (0.5, 12.0, 0.1), "freqy": (0.5, 12.0, 0.1),
    "slip": (-1.0, 1.0, 0.005), "size": (0.05, 0.9, 0.01),
    "rate": (0.05, 5.0, 0.05),
    "seconds": (0.05, 3.0, 0.01), "samples": (8, 2000, 4),
    "weight": (0.05, 1.0, 0.01), "taper": (0.0, 8.0, 0.1),
    "hue": (0, 1, 0.01), "sat": (0, 1, 0.01),
    "floor": (0.0, 0.3, 0.005),
    "glow": (0, 1, 0.01), "bloom": (0, 60, 1),
    "kick_bend": (0.0, 2.0, 0.01), "kick_time": (0.05, 2.0, 0.05),
    "hat_lift": (0.0, 1.0, 0.01), "hat_time": (0.02, 1.0, 0.01),
    "intro_open": (0.02, 1.0, 0.01), "arrive": (0.1, 1.0, 0.01),
    "outro": (0, 60, 1),
}


CONTROLS: tuple[Control, ...] = (
    Control("figure", "Figure",
            "The ratio between the two axes: simple loops at one end, a dense "
            "knot at the other.",
            "curve.freqx", {"curve.freqx": (2.0, 7.0),
                            "curve.slip": (0.01, 0.14)}),
    Control("persistence", "Persistence",
            "How much of the curve's recent past is still glowing behind it.",
            "trail.seconds", {"trail.seconds": (0.12, 1.4),
                              "trail.taper": (4.5, 1.2)}),
    Control("bend", "Bend",
            "How far a kick pulls the figure out of shape.",
            "beat.kick_bend", {"beat.kick_bend": (0.0, 1.1),
                               "beat.kick_time": (0.2, 0.8)}),
    Control("glow", "Glow",
            "The phosphor bloom around the line.",
            "look.glow", {"look.glow": (0.15, 0.9),
                          "look.bloom": (8.0, 40.0)}),
)


def reconcile(params: "Params") -> None:
    f, c, tr, lk, b = (params.frame, params.curve, params.trail, params.look,
                       params.beat)
    f.scale = min(1.0, max(0.1, f.scale))
    c.freqx = max(0.1, c.freqx)
    c.freqy = max(0.1, c.freqy)
    # Equal frequencies draw a straight line rather than a figure.
    if abs(c.freqx - c.freqy) < 0.05:
        c.freqy = c.freqx * 0.667
    c.size = min(0.9, max(0.03, c.size))
    tr.seconds = max(0.01, tr.seconds)
    tr.samples = max(8, int(tr.samples))
    tr.weight = min(1.0, max(0.05, tr.weight))
    lk.floor = min(lk.floor, max(0.0, tr.weight - 0.005))
    b.intro_open = min(1.0, max(0.02, b.intro_open))
    b.arrive = min(1.0, max(0.1, b.arrive))
    b.outro = max(0.0, b.outro) or 1.0


control_values, apply_control, controls_payload = bind_controls(
    CONTROLS, reconcile)
