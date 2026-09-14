"""Approach's tunables: the words travel toward you.

Taken from the Chainsmokers' "Closer" lyric video, where the lyrics fly through
three-dimensional space over live action. The footage half is out of reach --
nothing in this pipeline has a video input -- but the type half is the part that
makes that video recognisable, and it is reachable.

The vocabulary here is depth: how far away a word is born, how fast it comes,
and how the frame thins with distance. There is no grid, no glyph ramp and no
band, because the words are not on a lattice at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .._controls import Control, bind_controls


@dataclass
class Stage:
    """The frame, and where the vanishing point sits in it."""

    width: int = 720
    height: int = 1280
    font: str = "Arial"
    # 0..1 across the frame. Off-centre reads as a camera looking down a street
    # rather than as a tunnel, which is the difference between the reference and
    # a screensaver.
    vanish_x: float = 0.5
    vanish_y: float = 0.46


@dataclass
class Travel:
    """How a word crosses the space between its cue and the camera."""

    # Depth is in arbitrary units where 1.0 is "as wide as the frame". A word is
    # born at `far_z` and is gone once it passes `near_z`.
    far_z: float = 7.0
    near_z: float = 0.55
    # Seconds to cross that whole distance. Shorter than a word's gap and words
    # arrive alone; longer and several are in flight at once, which is the look.
    seconds: float = 2.6
    # How far off the axis a word may be born, as a fraction of the frame. Zero
    # sends every word straight down the middle and they stack into one blur.
    spread: float = 0.42
    # Font size in pixels at depth 1.0. Everything else follows from this and
    # the depth a word is at.
    size_at_one: float = 190.0


@dataclass
class Depth:
    """The slabs the space is quantised into.

    A Text TOP has ONE font size for its whole Specification DAT, so continuous
    perspective is not available: the space is cut into `layers` slabs, each its
    own Text TOP at its own fixed size, and a word is drawn by whichever slab is
    nearest its depth. More slabs means smoother travel and more operators.
    """

    layers: int = 5
    # Brightness of the farthest slab relative to the nearest. This is the fog,
    # and it is what makes the depth read at all.
    fog: float = 0.22
    # Blur on the farthest slab only, in pixels: distance should cost focus as
    # well as size and brightness.
    haze: float = 4.0


@dataclass
class Look:
    hue: float = 0.58
    sat: float = 0.18
    peak: float = 0.90
    floor: float = 0.02
    glow: float = 0.30
    bloom: float = 16.0


@dataclass
class Beat:
    """What the drums do to a picture whose subject is the words."""

    # The room lifts on a kick, not the type: the words belong to the cue table.
    kick_lift: float = 0.09
    kick_time: float = 0.22
    intro_open: float = 0.32
    arrive: float = 0.85
    outro: float = 10.0


@dataclass
class Params:
    stage: Stage = field(default_factory=Stage)
    travel: Travel = field(default_factory=Travel)
    depth: Depth = field(default_factory=Depth)
    look: Look = field(default_factory=Look)
    beat: Beat = field(default_factory=Beat)

    def validate(self) -> list[str]:
        out: list[str] = []
        s, tr, d, lk, b = (self.stage, self.travel, self.depth, self.look,
                           self.beat)
        for name, v in (("vanish_x", s.vanish_x), ("vanish_y", s.vanish_y)):
            if not (0.0 <= v <= 1.0):
                out.append(f"{name} {v} is outside the frame")
        if tr.near_z <= 0:
            out.append(
                "near_z must be positive; at zero a word is infinitely large "
                "and the projection divides by nothing")
        if tr.far_z <= tr.near_z:
            out.append(
                f"far_z {tr.far_z} must be beyond near_z {tr.near_z}, or there "
                "is no distance for a word to cross")
        if tr.seconds <= 0:
            out.append("seconds must be positive; it is a journey time")
        if tr.size_at_one <= 0:
            out.append("size_at_one must be positive; it is a font size")
        if d.layers < 2:
            out.append(
                f"layers {d.layers} gives no depth at all; two slabs is the "
                "least that can read as near and far")
        if not (0.0 < d.fog <= 1.0):
            out.append(f"fog {d.fog} must be above 0 and at most 1")
        if d.haze < 0:
            out.append("haze is a blur size and cannot be negative")
        if lk.floor >= lk.peak:
            out.append("floor must be below peak")
        # Brightness stacks. The ground is composited onto the type with `add`,
        # so those two sum; the bloom goes on with `maximum` and cannot exceed
        # what it was blurred from.
        stacked = lk.peak + lk.floor + b.kick_lift
        if stacked > 1.02:
            out.append(
                f"peak {lk.peak} on a ground of {lk.floor} lifted {b.kick_lift} "
                f"by a kick reaches ~{stacked:.2f} at the output")
        if b.outro <= 0:
            out.append("outro must be positive; it is the length of the ending")
        if not (0.0 < b.intro_open <= 1.0):
            out.append(f"intro_open {b.intro_open} must be above 0 and at most 1")
        if not (0.0 < b.arrive <= 1.0):
            out.append(f"arrive {b.arrive} must be above 0 and at most 1")
        return out

    def regions(self) -> dict[str, tuple[int, int, int, int]]:
        """Words converge on the vanishing point, so that is where the light is.

        Not the `band`/`lower` pair the grid types declare -- those names mean
        "inside the character band" and there is no band here.
        """
        s = self.stage
        w = int(s.width * 0.8)
        h = int(s.height * 0.5)
        x = int(max(0, min(s.width - w, s.width * s.vanish_x - w / 2)))
        y = int(max(0, min(s.height - h, s.height * s.vanish_y - h / 2)))
        return {"lane": (x, y, w, h)}


def slab_depths(params: "Params") -> list[float]:
    """The depth each slab stands at, nearest first.

    Geometric rather than linear, because apparent size goes as 1/z: spaced
    linearly, the near slabs would be indistinguishable from each other and the
    far ones would jump. Shared by `build` (which needs the font sizes) and the
    field (which needs to pick a slab), so the two cannot disagree.
    """
    d, tr = params.depth, params.travel
    n = max(2, int(d.layers))
    lo, hi = max(1e-6, tr.near_z), max(tr.near_z * 1.0001, tr.far_z)
    ratio = hi / lo
    return [lo * (ratio ** (i / (n - 1.0))) for i in range(n)]


RANGES: dict[str, tuple] = {
    "width": (240, 2160, 2), "height": (240, 3840, 2),
    "vanish_x": (0.0, 1.0, 0.01), "vanish_y": (0.0, 1.0, 0.01),
    "far_z": (1.5, 30.0, 0.5), "near_z": (0.1, 2.0, 0.05),
    "seconds": (0.4, 12.0, 0.1), "spread": (0.0, 1.2, 0.01),
    "size_at_one": (20.0, 600.0, 5.0),
    "layers": (2, 7, 1), "fog": (0.02, 1.0, 0.01), "haze": (0.0, 24.0, 0.5),
    "hue": (0, 1, 0.01), "sat": (0, 1, 0.01),
    "peak": (0.2, 1.0, 0.01), "floor": (0.0, 0.3, 0.005),
    "glow": (0, 1, 0.01), "bloom": (0, 60, 1),
    "kick_lift": (0.0, 0.6, 0.01), "kick_time": (0.05, 2.0, 0.05),
    "intro_open": (0.02, 1.0, 0.01), "arrive": (0.1, 1.0, 0.01),
    "outro": (0, 60, 1),
}


CONTROLS: tuple[Control, ...] = (
    Control("speed", "Speed",
            "How fast a word crosses the distance to the camera.",
            "travel.seconds", {"travel.seconds": (5.0, 1.0)}),
    Control("depth", "Depth",
            "How far away a word starts, and how much the distance thins it.",
            "travel.far_z", {"travel.far_z": (3.0, 16.0),
                             "depth.fog": (0.5, 0.08)}),
    Control("scatter", "Scatter",
            "How far off the centre line the words are thrown.",
            "travel.spread", {"travel.spread": (0.05, 0.85)}),
    Control("glow", "Glow",
            "The halo around the type, and how far it spreads.",
            "look.glow", {"look.glow": (0.05, 0.65),
                          "look.bloom": (4.0, 36.0)}),
)


def reconcile(params: "Params") -> None:
    """Settle the relationships `validate()` insists on."""
    s, tr, d, lk, b = (params.stage, params.travel, params.depth, params.look,
                       params.beat)
    s.vanish_x = min(1.0, max(0.0, s.vanish_x))
    s.vanish_y = min(1.0, max(0.0, s.vanish_y))
    tr.near_z = max(0.05, tr.near_z)
    tr.far_z = max(tr.near_z * 1.5, tr.far_z)
    tr.seconds = max(0.1, tr.seconds)
    tr.size_at_one = max(1.0, tr.size_at_one)
    tr.spread = max(0.0, tr.spread)
    d.layers = max(2, int(d.layers))
    d.fog = min(1.0, max(0.02, d.fog))
    d.haze = max(0.0, d.haze)
    lk.floor = min(lk.floor, lk.peak - 0.01)
    # In order of what may give way: the kick's lift of the room first, then
    # the room itself. Both are matters of taste. The type's own brightness is
    # a matter of legibility and stays where it was asked to be.
    over = (lk.peak + lk.floor + b.kick_lift) - 1.02
    if over > 0:
        give = min(over, b.kick_lift)
        b.kick_lift, over = b.kick_lift - give, over - give
    if over > 0:
        lk.floor = max(0.0, lk.floor - over)
    b.intro_open = min(1.0, max(0.02, b.intro_open))
    b.arrive = min(1.0, max(0.1, b.arrive))
    b.outro = max(0.0, b.outro) or 1.0


control_values, apply_control, controls_payload = bind_controls(
    CONTROLS, reconcile)
