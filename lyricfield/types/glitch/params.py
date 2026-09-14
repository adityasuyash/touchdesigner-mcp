"""Glitch's tunables: the words, torn.

The corruption vocabulary -- CRT scanlines, RGB channels pulled apart, blocks of
the image displaced sideways. It descends from demoscene glitch art and is half
of what makes the vaporwave look read; `horizon` has the other half, the neon
grid and the banded sun.

The tunables are about damage, not about layout: how often the picture tears,
how far, how wide a torn block is, and how hard the channels separate.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .._controls import Control, bind_controls


@dataclass
class Stage:
    """The frame, and the type sitting in it before anything is done to it."""

    width: int = 720
    height: int = 1280
    font: str = "Arial"
    size: float = 78.0
    # Where the line sits, 0 at the top and 1 at the bottom.
    line_y: float = 0.5
    # How many words of the current line are held on screen at once. The line
    # assembles as it is sung rather than appearing whole.
    hold: float = 2.4


@dataclass
class Tear:
    """Blocks of the picture, displaced sideways.

    The displacement is written as a remap field, so the tear moves the pixels
    that are there rather than drawing over them -- which is what makes it read
    as a damaged signal rather than as a rectangle someone pasted on.
    """

    # How far a torn block slides, as a fraction of the frame's width.
    throw: float = 0.09
    # How tall a block is, as a fraction of the frame's height.
    band: float = 0.06
    # How much of the frame is torn at rest, 0..1. A kick throws this up.
    rest: float = 0.06
    kick_lift: float = 0.7
    kick_time: float = 0.20
    # How fast the tear pattern reshuffles, in rerolls per second.
    churn: float = 9.0


@dataclass
class Split:
    """The channels, pulled apart."""

    # Separation at rest, as a fraction of the frame's width. Called `gap`
    # rather than `rest` because `tear` already has a `rest` and the sections
    # are flattened into ONE namespace before they are pushed -- two sections
    # sharing a key silently keep whichever came last.
    gap: float = 0.004
    snare_lift: float = 0.020
    snare_time: float = 0.18


@dataclass
class Lines:
    """Scanlines: the CRT half of the look."""

    # How many dark lines down the frame.
    count: float = 240.0
    # How dark they get. At 1.0 every other line is black and the type is
    # unreadable; this is a texture, not a shutter.
    depth: float = 0.35
    # Lines per second the pattern rolls down the frame. Zero is a still CRT,
    # which reads as a screenshot rather than as a screen.
    roll: float = 42.0
    hat_lift: float = 0.18
    hat_time: float = 0.12


@dataclass
class Look:
    hue: float = 0.52
    sat: float = 0.10
    peak: float = 0.92
    floor: float = 0.015
    glow: float = 0.30
    bloom: float = 12.0


@dataclass
class Beat:
    intro_open: float = 0.30
    arrive: float = 0.85
    outro: float = 10.0


@dataclass
class Params:
    stage: Stage = field(default_factory=Stage)
    tear: Tear = field(default_factory=Tear)
    split: Split = field(default_factory=Split)
    lines: Lines = field(default_factory=Lines)
    look: Look = field(default_factory=Look)
    beat: Beat = field(default_factory=Beat)

    def validate(self) -> list[str]:
        out: list[str] = []
        s, tr, sp, ln, lk, b = (self.stage, self.tear, self.split, self.lines,
                                self.look, self.beat)
        if s.size <= 0:
            out.append("size must be positive; it is a font size")
        if not (0.0 <= s.line_y <= 1.0):
            out.append(f"line_y {s.line_y} is outside the frame")
        if s.hold <= 0:
            out.append("hold must be positive; it is how long a word stays up")
        if tr.band <= 0:
            out.append("band must be positive; it is the height of a torn block")
        if not (0.0 <= tr.rest <= 1.0):
            out.append(f"rest {tr.rest} must be a share of the frame, 0 to 1")
        if tr.rest + tr.kick_lift > 1.0:
            out.append(
                f"a resting tear of {tr.rest} lifted {tr.kick_lift} by a kick "
                "would tear the whole frame at once, which reads as noise "
                "rather than as damage")
        if tr.churn < 0:
            out.append("churn cannot be negative; it is a rate")
        for name, v in (("kick_time", tr.kick_time),
                        ("snare_time", sp.snare_time),
                        ("hat_time", ln.hat_time)):
            if v <= 0:
                out.append(f"{name} must be positive; it is a decay")
        if ln.count < 1:
            out.append("count must be at least 1; it is a number of scanlines")
        if not (0.0 <= ln.depth < 1.0):
            out.append(
                f"depth {ln.depth} must be below 1; at 1 the dark lines are "
                "fully black and the type cannot be read through them")
        if ln.depth + ln.hat_lift >= 1.0:
            out.append(
                f"scanlines at {ln.depth} lifted {ln.hat_lift} by the hats "
                "reach full black")
        if lk.floor >= lk.peak:
            out.append("floor must be below peak")
        stacked = lk.peak + lk.floor
        if stacked > 1.02:
            out.append(
                f"peak {lk.peak} on a ground of {lk.floor} reaches "
                f"~{stacked:.2f} at the output")
        if b.outro <= 0:
            out.append("outro must be positive; it is the length of the ending")
        if not (0.0 < b.intro_open <= 1.0):
            out.append(f"intro_open {b.intro_open} must be above 0 and at most 1")
        if not (0.0 < b.arrive <= 1.0):
            out.append(f"arrive {b.arrive} must be above 0 and at most 1")
        return out

    def regions(self) -> dict[str, tuple[int, int, int, int]]:
        """The line's own band. The tear throws pixels sideways, never up, so
        the light stays in the strip the type was drawn in."""
        s = self.stage
        h = int(s.height * 0.3)
        y = int(max(0, min(s.height - h, s.height * s.line_y - h / 2)))
        return {"line": (0, y, s.width, h)}


RANGES: dict[str, tuple] = {
    "width": (240, 2160, 2), "height": (240, 3840, 2),
    "size": (10.0, 400.0, 1.0), "line_y": (0.0, 1.0, 0.01),
    "hold": (0.2, 10.0, 0.1),
    "throw": (0.0, 0.5, 0.005), "band": (0.005, 0.5, 0.005),
    "rest": (0.0, 1.0, 0.01), "gap": (0.0, 0.1, 0.001),
    "kick_lift": (0.0, 1.0, 0.01), "kick_time": (0.02, 2.0, 0.01),
    "churn": (0.0, 60.0, 0.5),
    "snare_lift": (0.0, 0.1, 0.001), "snare_time": (0.02, 2.0, 0.01),
    "count": (1.0, 900.0, 1.0), "depth": (0.0, 0.95, 0.01),
    "roll": (-400.0, 400.0, 1.0),
    "hat_lift": (0.0, 0.8, 0.01), "hat_time": (0.02, 1.0, 0.01),
    "hue": (0, 1, 0.01), "sat": (0, 1, 0.01),
    "peak": (0.2, 1.0, 0.01), "floor": (0.0, 0.3, 0.005),
    "glow": (0, 1, 0.01), "bloom": (0, 60, 1),
    "intro_open": (0.02, 1.0, 0.01), "arrive": (0.1, 1.0, 0.01),
    "outro": (0, 60, 1),
}


CONTROLS: tuple[Control, ...] = (
    Control("damage", "Damage",
            "How much of the picture tears, and how far it slides.",
            "tear.rest", {"tear.rest": (0.0, 0.35),
                          "tear.throw": (0.02, 0.22)}),
    Control("fringe", "Fringe",
            "How far the red and blue channels pull apart.",
            "split.gap", {"split.gap": (0.0, 0.02),
                          "split.snare_lift": (0.002, 0.05)}),
    Control("scanlines", "Scanlines",
            "How heavy the CRT lines are, and how fine.",
            "lines.depth", {"lines.depth": (0.05, 0.7),
                            "lines.count": (90.0, 500.0)}),
    Control("glow", "Glow",
            "The halo around the type, and how far it spreads.",
            "look.glow", {"look.glow": (0.05, 0.65),
                          "look.bloom": (3.0, 30.0)}),
)


def reconcile(params: "Params") -> None:
    """Settle the relationships `validate()` insists on."""
    s, tr, sp, ln, lk, b = (params.stage, params.tear, params.split,
                            params.lines, params.look, params.beat)
    s.size = max(1.0, s.size)
    s.line_y = min(1.0, max(0.0, s.line_y))
    s.hold = max(0.05, s.hold)
    tr.band = max(0.005, tr.band)
    tr.rest = min(1.0, max(0.0, tr.rest))
    tr.churn = max(0.0, tr.churn)
    tr.kick_time = max(0.01, tr.kick_time)
    sp.snare_time = max(0.01, sp.snare_time)
    ln.hat_time = max(0.01, ln.hat_time)
    ln.count = max(1.0, ln.count)
    # The kick's share gives way, not the resting damage: `rest` is the style's
    # own character and the lift is the part that is merely loud.
    if tr.rest + tr.kick_lift > 1.0:
        tr.kick_lift = max(0.0, 1.0 - tr.rest)
    ln.depth = min(0.95, max(0.0, ln.depth))
    if ln.depth + ln.hat_lift >= 1.0:
        ln.hat_lift = max(0.0, 0.99 - ln.depth)
    lk.floor = min(lk.floor, lk.peak - 0.01)
    over = (lk.peak + lk.floor) - 1.02
    if over > 0:
        lk.floor = max(0.0, lk.floor - over)
    b.intro_open = min(1.0, max(0.02, b.intro_open))
    b.arrive = min(1.0, max(0.1, b.arrive))
    b.outro = max(0.0, b.outro) or 1.0


control_values, apply_control, controls_payload = bind_controls(
    CONTROLS, reconcile)
