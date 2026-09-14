"""Spectrum's tunables: the beat as bars.

The most recognisable music visual there is, and the last obvious one the system
did not have. It is also the only renderer here that needs data none of the
others do -- `bands.tsv`, how loud each frequency band is over time -- because
bars are not a reaction to the beat, they ARE the spectrum.

The vocabulary is a bar chart: how many, how wide, how they are anchored, and
how the caps that mark each peak fall back.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .._controls import Control, bind_controls


@dataclass
class Frame:
    width: int = 720
    height: int = 1280
    scale: float = 0.5


@dataclass
class Bars:
    """The chart itself."""

    # How many bars. Fewer than the measured bands means neighbours are averaged
    # together, which is what you want on a narrow frame.
    count: int = 24
    # Share of each bar's slot that is actually inked. 1.0 is a solid block with
    # no gaps, which reads as a heightmap rather than as bars.
    fill: float = 0.62
    # Tallest a bar may get, as a share of the frame's height.
    reach: float = 0.68
    # Where the bars stand: 0 the bottom, 0.5 the middle, 1 the top.
    floor_at: float = 0.92
    # Mirrored bars grow both ways from the baseline. The other iconic form.
    mirror: bool = False
    # How quickly a bar follows the measurement down. Rising is instant -- a
    # spectrum that is slow to rise misses every transient, which is the only
    # thing a bar chart is good at showing.
    settle: float = 0.16


@dataclass
class Caps:
    """The peak-hold marks that sit above each bar and fall back."""

    on: bool = True
    # Thickness as a share of the frame's height.
    thick: float = 0.006
    # How far a cap falls per second, as a share of the frame's height.
    fall: float = 0.55
    # How long it hangs at a new peak before it starts falling.
    hang: float = 0.22


@dataclass
class Look:
    # Bars are tinted across their width, which is what makes a spectrum read as
    # a spectrum rather than as a row of blocks: low bands one colour, high
    # bands another.
    hue: float = 0.55
    hue_span: float = 0.28
    sat: float = 0.55
    peak: float = 0.92
    floor: float = 0.02
    glow: float = 0.28
    bloom: float = 12.0


@dataclass
class Beat:
    intro_open: float = 0.30
    arrive: float = 0.85
    outro: float = 10.0


@dataclass
class Params:
    frame: Frame = field(default_factory=Frame)
    bars: Bars = field(default_factory=Bars)
    caps: Caps = field(default_factory=Caps)
    look: Look = field(default_factory=Look)
    beat: Beat = field(default_factory=Beat)

    def validate(self) -> list[str]:
        out: list[str] = []
        f, br, cp, lk, b = (self.frame, self.bars, self.caps, self.look,
                            self.beat)
        if not (0.1 <= f.scale <= 1.0):
            out.append(f"scale {f.scale} must be between 0.1 and 1")
        if br.count < 1:
            out.append("count must be at least 1; it is a number of bars")
        if not (0.0 < br.fill <= 1.0):
            out.append(f"fill {br.fill} must be above 0 and at most 1")
        if not (0.0 < br.reach <= 1.0):
            out.append(f"reach {br.reach} must be above 0 and at most 1")
        if not (0.0 <= br.floor_at <= 1.0):
            out.append(f"floor_at {br.floor_at} is outside the frame")
        if br.settle < 0:
            out.append("settle cannot be negative; it is a fall time")
        if br.mirror and br.floor_at > 0.9:
            out.append(
                f"mirrored bars grow both ways from {br.floor_at}, so the half "
                "growing downward is off the bottom of the frame")
        if cp.thick <= 0:
            out.append("thick must be positive; it is a cap's height")
        if cp.fall < 0:
            out.append("fall cannot be negative; it is a rate")
        if cp.hang < 0:
            out.append("hang cannot be negative; it is a delay")
        if lk.floor >= lk.peak:
            out.append("floor must be below peak")
        if not (0.0 <= lk.hue_span <= 1.0):
            out.append(f"hue_span {lk.hue_span} must be between 0 and 1")
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


RANGES: dict[str, tuple] = {
    "width": (240, 2160, 2), "height": (240, 3840, 2),
    "scale": (0.1, 1.0, 0.05),
    "count": (1, 96, 1), "fill": (0.05, 1.0, 0.01),
    "reach": (0.05, 1.0, 0.01), "floor_at": (0.0, 1.0, 0.01),
    "mirror": (0, 1, 1), "settle": (0.0, 2.0, 0.01),
    "on": (0, 1, 1), "thick": (0.001, 0.05, 0.001),
    "fall": (0.0, 4.0, 0.05), "hang": (0.0, 2.0, 0.01),
    "hue": (0, 1, 0.01), "hue_span": (0, 1, 0.01), "sat": (0, 1, 0.01),
    "peak": (0.2, 1.0, 0.01), "floor": (0.0, 0.3, 0.005),
    "glow": (0, 1, 0.01), "bloom": (0, 60, 1),
    "intro_open": (0.02, 1.0, 0.01), "arrive": (0.1, 1.0, 0.01),
    "outro": (0, 60, 1),
}


CONTROLS: tuple[Control, ...] = (
    Control("bars", "Bars",
            "How many bars, and how much of each slot is inked.",
            "bars.count", {"bars.count": (8, 64),
                           "bars.fill": (0.9, 0.45)}),
    Control("response", "Response",
            "How quickly a bar follows the music back down.",
            "bars.settle", {"bars.settle": (0.5, 0.03)}),
    Control("caps", "Caps",
            "The peak marks above each bar, and how fast they fall.",
            "caps.thick", {"caps.thick": (0.002, 0.016),
                           "caps.fall": (1.6, 0.18)}),
    Control("glow", "Glow",
            "The halo around the bars, and how far it spreads.",
            "look.glow", {"look.glow": (0.04, 0.6),
                          "look.bloom": (3.0, 30.0)}),
)


def reconcile(params: "Params") -> None:
    """Settle the relationships `validate()` insists on."""
    f, br, cp, lk, b = (params.frame, params.bars, params.caps, params.look,
                        params.beat)
    f.scale = min(1.0, max(0.1, f.scale))
    br.count = max(1, int(br.count))
    br.fill = min(1.0, max(0.05, br.fill))
    br.reach = min(1.0, max(0.05, br.reach))
    br.floor_at = min(1.0, max(0.0, br.floor_at))
    br.settle = max(0.0, br.settle)
    # Mirrored bars need room on both sides of the baseline, so the baseline
    # comes in rather than the mirroring being silently ignored.
    if br.mirror and br.floor_at > 0.9:
        br.floor_at = 0.5
    cp.thick = max(0.001, cp.thick)
    cp.fall = max(0.0, cp.fall)
    cp.hang = max(0.0, cp.hang)
    lk.hue_span = min(1.0, max(0.0, lk.hue_span))
    lk.floor = min(lk.floor, lk.peak - 0.01)
    over = (lk.peak + lk.floor) - 1.02
    if over > 0:
        lk.floor = max(0.0, lk.floor - over)
    b.intro_open = min(1.0, max(0.02, b.intro_open))
    b.arrive = min(1.0, max(0.1, b.arrive))
    b.outro = max(0.0, b.outro) or 1.0


control_values, apply_control, controls_payload = bind_controls(
    CONTROLS, reconcile)
