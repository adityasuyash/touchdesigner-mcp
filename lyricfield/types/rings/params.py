"""Rings' tunables: the beat as circles from the centre.

Nothing is imported from `lyric_grid`. There is no grid to describe -- the
Script TOP here runs at frame resolution and writes pixels, so the vocabulary
is radius, thickness and speed rather than rows, columns and glyphs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .._controls import Control, bind_controls


@dataclass
class Frame:
    """The canvas the field is drawn into.

    `scale` is the one that matters for cost: the field is computed at this
    fraction of the frame and the network scales it up. At 0.5 a 720x1280
    frame is 230k pixels a frame instead of 920k, and every ring here is soft
    enough that nobody can tell.
    """

    width: int = 720
    height: int = 1280
    scale: float = 0.5


@dataclass
class Ring:
    """A ring is born on a kick and expands until it leaves the frame."""

    speed: float = 0.62      # frame-heights per second
    thick: float = 0.035     # thickness as a fraction of frame height
    birth: float = 0.75      # brightness at birth
    decay: float = 1.1       # seconds to fade to nothing
    # A ring starts as a small circle rather than a point: born at zero radius
    # it reads as a flash at the centre, not as a ring leaving it.
    seed: float = 0.04
    limit: int = 14          # most rings alive at once


@dataclass
class Spoke:
    """A snare throws arms out from the centre."""

    count: int = 12
    peak: float = 0.45
    fade: float = 0.28
    taper: float = 2.2       # how quickly a spoke thins with radius


@dataclass
class Grain:
    """The hi-hats, as a fine rotating texture."""

    lift: float = 0.14
    settle: float = 0.22
    spin: float = 0.35       # turns per second
    freq: float = 34.0       # angular cycles around the circle


@dataclass
class Look:
    hue: float = 0.54
    sat: float = 0.45
    # The centre is brighter than the rim, always: it is where everything is
    # born, and a flat field of rings reads as wallpaper.
    core: float = 0.22
    floor: float = 0.015
    glow: float = 0.34
    bloom: float = 18.0


@dataclass
class Beat:
    intro_open: float = 0.30
    arrive: float = 0.80
    outro: float = 12.0


@dataclass
class Params:
    frame: Frame = field(default_factory=Frame)
    ring: Ring = field(default_factory=Ring)
    spoke: Spoke = field(default_factory=Spoke)
    grain: Grain = field(default_factory=Grain)
    look: Look = field(default_factory=Look)
    beat: Beat = field(default_factory=Beat)

    def validate(self) -> list[str]:
        out: list[str] = []
        f, r, sp, gr, lk, b = (self.frame, self.ring, self.spoke, self.grain,
                               self.look, self.beat)
        if not (0.1 <= f.scale <= 1.0):
            out.append(f"scale {f.scale} must be between 0.1 and 1")
        if r.speed <= 0:
            out.append("speed must be positive; a ring has to leave the centre")
        if r.thick <= 0:
            out.append("thick must be positive; it is a ring's width")
        if r.seed <= 0:
            out.append(
                "seed must be positive, or a ring is born as a point and reads "
                "as a flash at the centre rather than a ring leaving it")
        if r.limit < 1:
            out.append("limit must be at least 1")
        if sp.count < 1:
            out.append("count must be at least 1; it is the number of spokes")
        if lk.floor >= lk.core:
            out.append("floor must be below core")
        # Brightness stacks at the output. Everything here is added into one
        # field and then bloomed with `maximum`, so the additive terms are what
        # must stay under white.
        stacked = lk.core + r.birth + sp.peak * 0.5 + gr.lift
        if stacked > 1.35:
            out.append(
                f"core {lk.core} plus a ring at {r.birth}, a snare at "
                f"{sp.peak} and hats at {gr.lift} reach ~{stacked:.2f}")
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
    "speed": (0.05, 3.0, 0.01), "thick": (0.002, 0.3, 0.001),
    "birth": (0.0, 1.2, 0.01), "decay": (0.05, 6.0, 0.05),
    "fade": (0.05, 3.0, 0.01), "settle": (0.05, 3.0, 0.01),
    "seed": (0.005, 0.4, 0.005), "limit": (1, 48, 1),
    "count": (1, 64, 1), "peak": (0.0, 1.0, 0.01),
    "taper": (0.0, 8.0, 0.1),
    "lift": (0.0, 0.8, 0.01), "spin": (-3.0, 3.0, 0.01),
    "freq": (1.0, 160.0, 1.0),
    "hue": (0, 1, 0.01), "sat": (0, 1, 0.01),
    "core": (0.0, 0.8, 0.01), "floor": (0.0, 0.3, 0.005),
    "glow": (0, 1, 0.01), "bloom": (0, 60, 1),
    "intro_open": (0.02, 1.0, 0.01), "arrive": (0.1, 1.0, 0.01),
    "outro": (0, 60, 1),
}


CONTROLS: tuple[Control, ...] = (
    Control("force", "Force",
            "How hard a kick lands and how long its ring takes to fade.",
            "ring.birth", {"ring.birth": (0.3, 1.1),
                           "ring.decay": (0.5, 2.2)}),
    Control("spread", "Spread",
            "How fast rings travel outward, and how thick they are.",
            "ring.speed", {"ring.speed": (0.2, 1.4),
                           "ring.thick": (0.012, 0.09)}),
    Control("texture", "Texture",
            "The hi-hat grain turning over the whole field.",
            "grain.lift", {"grain.lift": (0.0, 0.34),
                           "grain.freq": (12.0, 90.0)}),
    Control("glow", "Glow",
            "The halo around everything, and how far it spreads.",
            "look.glow", {"look.glow": (0.05, 0.7),
                          "look.bloom": (4.0, 40.0)}),
)


def reconcile(params: "Params") -> None:
    """Settle the relationships `validate()` insists on."""
    f, r, sp, gr, lk, b = (params.frame, params.ring, params.spoke,
                           params.grain, params.look, params.beat)
    f.scale = min(1.0, max(0.1, f.scale))
    r.speed = max(0.01, r.speed)
    r.thick = max(0.001, r.thick)
    r.seed = max(0.005, r.seed)
    r.limit = max(1, int(r.limit))
    sp.count = max(1, int(sp.count))
    lk.floor = min(lk.floor, max(0.0, lk.core - 0.005))
    # When the stack is too bright the ring gives way first: it is the loudest
    # term and the one a person is most likely to have pushed.
    over = (lk.core + r.birth + sp.peak * 0.5 + gr.lift) - 1.35
    if over > 0:
        r.birth = max(0.0, r.birth - over)
    b.intro_open = min(1.0, max(0.02, b.intro_open))
    b.arrive = min(1.0, max(0.1, b.arrive))
    b.outro = max(0.0, b.outro) or 1.0


control_values, apply_control, controls_payload = bind_controls(
    CONTROLS, reconcile)
