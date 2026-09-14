"""Strata's tunables: the beat as solid bands.

Deliberately the opposite of `rings` in every axis that matters. Rings are
curved, soft and centred; these are straight, hard-edged and stacked. Two beat
renderers that could be confused with each other would be two renderers doing
one job, which is the mistake this whole pass exists to undo.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .._controls import Control, bind_controls


@dataclass
class Frame:
    width: int = 720
    height: int = 1280
    # Bands are hard-edged, so the field is computed closer to full size than
    # a soft renderer needs -- at a quarter the edges would visibly stair.
    scale: float = 0.75


@dataclass
class Band:
    """The stack itself."""

    count: int = 9
    # The dark gap between bands, as a share of a band's own height. This is
    # what makes them read as separate bars rather than as one gradient.
    gap: float = 0.22
    rest: float = 0.10       # brightness of a band nothing has struck
    lit: float = 0.88        # ... and of one a kick just hit
    decay: float = 0.42      # seconds for a struck band to fall back
    # A kick hits one band, not all of them, and walks to the next each time.
    walk: int = 3


@dataclass
class Shear:
    """A snare slides the bands sideways, alternating direction."""

    amount: float = 0.16     # share of the frame's width
    snap: float = 0.30       # seconds to slide back


@dataclass
class Flicker:
    """The hi-hats, as a fast dark flicker across the gaps."""

    lift: float = 0.13
    fade: float = 0.13
    rows: float = 41.0       # how fine the flicker is


@dataclass
class Look:
    hue: float = 0.09
    sat: float = 0.55
    floor: float = 0.015
    # Low by design: hard edges and a wide bloom fight each other, and the
    # point of this renderer is the edge.
    glow: float = 0.14
    bloom: float = 6.0


@dataclass
class Beat:
    intro_open: float = 0.28
    arrive: float = 0.82
    outro: float = 12.0


@dataclass
class Params:
    frame: Frame = field(default_factory=Frame)
    band: Band = field(default_factory=Band)
    shear: Shear = field(default_factory=Shear)
    flicker: Flicker = field(default_factory=Flicker)
    look: Look = field(default_factory=Look)
    beat: Beat = field(default_factory=Beat)

    def validate(self) -> list[str]:
        out: list[str] = []
        f, bd, sh, fk, lk, b = (self.frame, self.band, self.shear,
                                self.flicker, self.look, self.beat)
        if not (0.1 <= f.scale <= 1.0):
            out.append(f"scale {f.scale} must be between 0.1 and 1")
        if bd.count < 2:
            out.append("count must be at least two; one band is not a stack")
        if not (0.0 <= bd.gap < 1.0):
            out.append(f"gap {bd.gap} must be between 0 and 1 of a band")
        if bd.rest >= bd.lit:
            out.append("rest must be below lit, or a kick darkens the band")
        if bd.walk < 0:
            out.append("walk cannot be negative")
        if lk.floor >= bd.rest:
            out.append("floor must be below rest")
        stacked = bd.lit + fk.lift + lk.glow * 0.5
        # A hair of tolerance: `reconcile` settles this to exactly the limit,
        # and binary floating point then puts it a billionth over.
        if stacked > 1.15 + 1e-6:
            out.append(
                f"a lit band at {bd.lit} with hats at {fk.lift} and glow "
                f"{lk.glow} reaches ~{stacked:.2f}")
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
    "count": (2, 48, 1), "gap": (0.0, 0.9, 0.01),
    "rest": (0.0, 0.6, 0.01), "lit": (0.1, 1.0, 0.01),
    "decay": (0.05, 3.0, 0.01), "walk": (0, 12, 1),
    "amount": (0.0, 0.6, 0.01), "snap": (0.05, 2.0, 0.01),
    "lift": (0.0, 0.6, 0.01), "fade": (0.02, 1.0, 0.01),
    "rows": (3.0, 160.0, 1.0),
    "hue": (0, 1, 0.01), "sat": (0, 1, 0.01),
    "floor": (0.0, 0.3, 0.005),
    "glow": (0, 1, 0.01), "bloom": (0, 60, 1),
    "intro_open": (0.02, 1.0, 0.01), "arrive": (0.1, 1.0, 0.01),
    "outro": (0, 60, 1),
}


CONTROLS: tuple[Control, ...] = (
    Control("weight", "Weight",
            "How many bands the frame is cut into, and how wide the dark "
            "between them is.",
            "band.count", {"band.count": (4, 22),
                           "band.gap": (0.35, 0.08)}),
    Control("strike", "Strike",
            "How bright a kick drives its band, and how long it takes to fall "
            "back.",
            "band.lit", {"band.lit": (0.4, 0.98),
                         "band.decay": (0.15, 0.9)}),
    Control("slide", "Slide",
            "How far a snare shoves the bands sideways.",
            "shear.amount", {"shear.amount": (0.0, 0.4),
                             "shear.snap": (0.12, 0.6)}),
    Control("glow", "Glow",
            "The halo. Low here on purpose: hard edges and a wide bloom fight "
            "each other.",
            "look.glow", {"look.glow": (0.0, 0.4),
                          "look.bloom": (2.0, 18.0)}),
)


def reconcile(params: "Params") -> None:
    f, bd, sh, fk, lk, b = (params.frame, params.band, params.shear,
                            params.flicker, params.look, params.beat)
    f.scale = min(1.0, max(0.1, f.scale))
    bd.count = max(2, int(bd.count))
    bd.gap = min(0.95, max(0.0, bd.gap))
    bd.walk = max(0, int(bd.walk))
    bd.rest = min(bd.rest, max(0.0, bd.lit - 0.01))
    lk.floor = min(lk.floor, max(0.0, bd.rest - 0.005))
    # The hats give way first, then the glow. A struck band keeps its
    # brightness: it is the thing the renderer is for.
    over = (bd.lit + fk.lift + lk.glow * 0.5) - 1.15
    if over > 0:
        give = min(over, fk.lift)
        fk.lift, over = fk.lift - give, over - give
    if over > 0:
        lk.glow = max(0.0, lk.glow - over * 2.0)
    b.intro_open = min(1.0, max(0.02, b.intro_open))
    b.arrive = min(1.0, max(0.1, b.arrive))
    b.outro = max(0.0, b.outro) or 1.0


control_values, apply_control, controls_payload = bind_controls(
    CONTROLS, reconcile)
