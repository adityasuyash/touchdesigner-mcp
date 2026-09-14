"""Orbit's tunables: the line rides a curve.

This is the renderer that proves the lattice is gone. Every other lyric type
here -- including the three grid ones -- places glyphs at positions something
else chose: a cell, a centred line, a wrapped block. Here each character is
given its own coordinate on a parametric curve, through the Text TOP's
Specification DAT, so the type can go anywhere at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .._controls import Control, bind_controls

# The curves a line can ride. Each is a closed parametric path in a unit
# square, so `radius` means the same thing whichever is chosen.
PATHS = (
    ("circle", "a ring, turning"),
    ("spiral", "winding inward as the line runs"),
    ("wave", "a travelling sine, read left to right"),
    ("lissajous", "a figure that crosses itself"),
)


@dataclass
class Frame:
    width: int = 720
    height: int = 1280


@dataclass
class Path:
    """Which curve, how big, and how fast it turns."""

    shape: str = "circle"
    radius: float = 0.33     # as a share of the frame's smaller side
    spin: float = 0.06       # turns a second
    # How far apart consecutive characters sit along the curve, as a share of
    # the whole path. Small values bunch the line; large ones spread it round.
    spread: float = 0.026
    # `lissajous` and `spiral` both need a second frequency to have a shape at
    # all; for a circle it does nothing and is left alone.
    twist: float = 3.0


@dataclass
class Line:
    font: str = "Arial"
    size: float = 46.0
    lead: float = 0.3
    hold: float = 0.9
    fade: float = 0.4


@dataclass
class Look:
    hue: float = 0.78
    sat: float = 0.4
    peak: float = 0.95
    floor: float = 0.02
    glow: float = 0.3
    bloom: float = 14.0


@dataclass
class Beat:
    # A kick breathes the whole curve outward.
    kick_push: float = 0.1
    kick_time: float = 0.3
    intro_open: float = 0.35
    arrive: float = 0.85
    outro: float = 11.0


@dataclass
class Params:
    frame: Frame = field(default_factory=Frame)
    path: Path = field(default_factory=Path)
    line: Line = field(default_factory=Line)
    look: Look = field(default_factory=Look)
    beat: Beat = field(default_factory=Beat)

    def validate(self) -> list[str]:
        out: list[str] = []
        f, p, ln, lk, b = (self.frame, self.path, self.line, self.look,
                           self.beat)
        known = [k for k, _ in PATHS]
        if p.shape not in known:
            out.append(f"unknown path {p.shape!r}; known: {', '.join(known)}")
        if not (0.02 < p.radius <= 0.9):
            out.append(f"radius {p.radius} would put the curve off the frame")
        if p.spread <= 0:
            out.append(
                "spread must be positive, or every character lands on the same "
                "point of the curve")
        if ln.size <= 0:
            out.append("size must be positive; it is a font size")
        if lk.floor >= lk.peak:
            out.append("floor must be below peak")
        stacked = lk.peak + lk.floor + b.kick_push
        if stacked > 1.08:
            out.append(
                f"peak {lk.peak} on a ground of {lk.floor} with a kick of "
                f"{b.kick_push} reaches ~{stacked:.2f}")
        if b.outro <= 0:
            out.append("outro must be positive; it is the length of the ending")
        if not (0.0 < b.intro_open <= 1.0):
            out.append(f"intro_open {b.intro_open} must be above 0 and at most 1")
        if not (0.0 < b.arrive <= 1.0):
            out.append(f"arrive {b.arrive} must be above 0 and at most 1")
        return out


RANGES: dict[str, tuple] = {
    "width": (240, 2160, 2), "height": (240, 3840, 2),
    "radius": (0.03, 0.9, 0.01), "spin": (-1.0, 1.0, 0.005),
    "spread": (0.002, 0.2, 0.001), "twist": (0.0, 12.0, 0.1),
    "size": (8, 200, 1), "lead": (0.0, 3.0, 0.05),
    "hold": (0.05, 5.0, 0.05), "fade": (0.02, 3.0, 0.01),
    "hue": (0, 1, 0.01), "sat": (0, 1, 0.01),
    "peak": (0.2, 1.0, 0.01), "floor": (0.0, 0.3, 0.005),
    "glow": (0, 1, 0.01), "bloom": (0, 60, 1),
    "kick_push": (0.0, 0.5, 0.01), "kick_time": (0.05, 2.0, 0.05),
    "intro_open": (0.02, 1.0, 0.01), "arrive": (0.1, 1.0, 0.01),
    "outro": (0, 60, 1),
}


CONTROLS: tuple[Control, ...] = (
    Control("size", "Size",
            "How large the curve is and how large the type on it is.",
            "path.radius", {"path.radius": (0.16, 0.46),
                            "line.size": (28.0, 66.0)}),
    Control("turn", "Turn",
            "How fast the curve rotates, and how far apart the characters sit "
            "along it.",
            "path.spin", {"path.spin": (0.0, 0.25),
                          "path.spread": (0.014, 0.04)}),
    Control("breath", "Breath",
            "How much a kick pushes the whole curve outward.",
            "beat.kick_push", {"beat.kick_push": (0.0, 0.3),
                               "beat.kick_time": (0.15, 0.6)}),
    Control("glow", "Glow",
            "The halo around the type, and how far it spreads.",
            "look.glow", {"look.glow": (0.05, 0.65),
                          "look.bloom": (4.0, 34.0)}),
)


def reconcile(params: "Params") -> None:
    f, p, ln, lk, b = (params.frame, params.path, params.line, params.look,
                       params.beat)
    known = [k for k, _ in PATHS]
    if p.shape not in known:
        p.shape = known[0]
    p.radius = min(0.9, max(0.03, p.radius))
    p.spread = max(0.002, p.spread)
    ln.size = max(1.0, ln.size)
    lk.floor = min(lk.floor, max(0.0, lk.peak - 0.005))
    # The kick gives way, then the ground. The type keeps its brightness.
    over = (lk.peak + lk.floor + b.kick_push) - 1.08
    if over > 0:
        give = min(over, b.kick_push)
        b.kick_push, over = b.kick_push - give, over - give
    if over > 0:
        lk.floor = max(0.0, lk.floor - over)
    b.intro_open = min(1.0, max(0.02, b.intro_open))
    b.arrive = min(1.0, max(0.1, b.arrive))
    b.outro = max(0.0, b.outro) or 1.0


control_values, apply_control, controls_payload = bind_controls(
    CONTROLS, reconcile)
