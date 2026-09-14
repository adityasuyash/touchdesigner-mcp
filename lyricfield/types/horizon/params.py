"""Horizon's tunables: a neon grid running to a banded sun.

The vaporwave one. It is the only renderer here that draws a *place* rather
than a pattern -- a floor in perspective, a horizon, a sun sitting on it -- and
the lyrics stand in that place rather than floating on black.

Two hues, not one, because the look is built on the collision of a hot and a
cold colour and a single hue cannot make it.
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
class Ground:
    """The floor, in perspective, running away to the horizon."""

    # Where the horizon sits, 0 at the top of the frame and 1 at the bottom.
    horizon: float = 0.52
    lanes: float = 16.0      # lines running away from the viewer
    rungs: float = 13.0      # lines crossing them
    speed: float = 0.55      # how fast the rungs run toward the viewer
    weight: float = 0.055    # line thickness, as a share of a cell
    lift: float = 0.9        # brightness of the lines
    haze: float = 2.1        # how quickly the floor fades toward the horizon


@dataclass
class Sun:
    """The disc on the horizon, cut by horizontal bands."""

    radius: float = 0.3      # as a share of frame width
    rise: float = 0.16       # how far its centre sits above the horizon
    bands: float = 9.0       # slices cut out of its lower half
    duck: float = 0.55       # share of each slice that is cut away
    glowr: float = 0.85      # brightness at its top, fading downward


@dataclass
class Line:
    """The lyrics, standing in the scene."""

    font: str = "Arial"
    size: float = 88.0
    lead: float = 0.3
    hold: float = 0.8
    fade: float = 0.4
    line_y: float = 0.3
    wrap: int = 14


@dataclass
class Look:
    # Hot and cold. The sky runs between them and the grid takes the cold one.
    hot: float = 0.92        # magenta
    cold: float = 0.52       # cyan
    sat: float = 0.85
    sky: float = 0.30        # brightness of the sky at the horizon
    floor: float = 0.02
    glow: float = 0.42
    bloom: float = 22.0


@dataclass
class Beat:
    # A kick pushes the floor's lines brighter; the scene is otherwise steady,
    # because a place that jumps on every beat stops being a place.
    kick_lift: float = 0.35
    kick_time: float = 0.28
    intro_open: float = 0.4
    arrive: float = 0.88
    outro: float = 12.0


@dataclass
class Params:
    frame: Frame = field(default_factory=Frame)
    ground: Ground = field(default_factory=Ground)
    sun: Sun = field(default_factory=Sun)
    line: Line = field(default_factory=Line)
    look: Look = field(default_factory=Look)
    beat: Beat = field(default_factory=Beat)

    def validate(self) -> list[str]:
        out: list[str] = []
        f, g, s, ln, lk, b = (self.frame, self.ground, self.sun, self.line,
                              self.look, self.beat)
        if not (0.1 <= f.scale <= 1.0):
            out.append(f"scale {f.scale} must be between 0.1 and 1")
        if not (0.05 < g.horizon < 0.95):
            out.append(
                f"horizon {g.horizon} leaves no room for a floor or a sky")
        if g.lanes <= 0 or g.rungs <= 0:
            out.append("lanes and rungs must both be positive")
        if not (0.0 < g.weight < 0.5):
            out.append(f"weight {g.weight} is not a usable line thickness")
        if s.radius <= 0:
            out.append("radius must be positive; it is the sun's size")
        if not (0.0 <= s.duck <= 1.0):
            out.append(f"duck {s.duck} must be between 0 and 1")
        if ln.wrap < 4:
            out.append("wrap below four characters cannot hold a word")
        if abs(lk.hot - lk.cold) < 0.12:
            out.append(
                f"hot {lk.hot} and cold {lk.cold} are nearly the same hue; the "
                "look is built on the collision of two")
        stacked = g.lift + b.kick_lift + lk.sky
        if stacked > 1.7:
            out.append(
                f"lines at {g.lift} lifted {b.kick_lift} over a sky of "
                f"{lk.sky} reach ~{stacked:.2f}")
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
    "horizon": (0.1, 0.9, 0.01), "lanes": (2.0, 60.0, 1.0),
    "rungs": (2.0, 60.0, 1.0), "speed": (-3.0, 3.0, 0.01),
    "weight": (0.005, 0.4, 0.005), "lift": (0.0, 1.2, 0.01),
    "haze": (0.0, 8.0, 0.1),
    "radius": (0.02, 0.9, 0.01), "rise": (-0.5, 0.8, 0.01),
    "size": (12, 300, 1),
    "bands": (0.0, 40.0, 1.0), "duck": (0.0, 1.0, 0.01),
    "glowr": (0.0, 1.2, 0.01),
    "lead": (0.0, 3.0, 0.05), "hold": (0.05, 5.0, 0.05),
    "fade": (0.02, 3.0, 0.01), "line_y": (0.0, 1.0, 0.01),
    "wrap": (4, 60, 1),
    "hot": (0, 1, 0.01), "cold": (0, 1, 0.01), "sat": (0, 1, 0.01),
    "sky": (0.0, 0.9, 0.01), "floor": (0.0, 0.3, 0.005),
    "glow": (0, 1, 0.01), "bloom": (0, 60, 1),
    "kick_lift": (0.0, 1.0, 0.01), "kick_time": (0.05, 2.0, 0.05),
    "intro_open": (0.02, 1.0, 0.01), "arrive": (0.1, 1.0, 0.01),
    "outro": (0, 60, 1),
}


CONTROLS: tuple[Control, ...] = (
    Control("depth", "Depth",
            "How far the floor runs and how dense its grid is.",
            "ground.rungs", {"ground.rungs": (6.0, 26.0),
                             "ground.lanes": (8.0, 30.0)}),
    Control("rush", "Rush",
            "How fast the floor runs toward you.",
            "ground.speed", {"ground.speed": (0.1, 1.6),
                             "beat.kick_lift": (0.1, 0.6)}),
    Control("sun", "Sun",
            "How large the disc is and how heavily it is sliced.",
            "sun.radius", {"sun.radius": (0.14, 0.46),
                         "sun.bands": (4.0, 18.0)}),
    Control("glow", "Glow",
            "The neon bleed over the whole scene.",
            "look.glow", {"look.glow": (0.1, 0.8),
                          "look.bloom": (8.0, 44.0)}),
)


def reconcile(params: "Params") -> None:
    f, g, s, ln, lk, b = (params.frame, params.ground, params.sun, params.line,
                          params.look, params.beat)
    f.scale = min(1.0, max(0.1, f.scale))
    g.horizon = min(0.94, max(0.06, g.horizon))
    g.lanes = max(1.0, g.lanes)
    g.rungs = max(1.0, g.rungs)
    g.weight = min(0.49, max(0.005, g.weight))
    s.radius = max(0.01, s.radius)
    s.duck = min(1.0, max(0.0, s.duck))
    ln.wrap = max(4, int(ln.wrap))
    ln.line_y = min(1.0, max(0.0, ln.line_y))
    # Keep the two hues apart: the look does not exist without the collision.
    if abs(lk.hot - lk.cold) < 0.12:
        lk.cold = (lk.hot + 0.5) % 1.0
    over = (g.lift + b.kick_lift + lk.sky) - 1.7
    if over > 0:
        give = min(over, b.kick_lift)
        b.kick_lift, over = b.kick_lift - give, over - give
    if over > 0:
        g.lift = max(0.0, g.lift - over)
    b.intro_open = min(1.0, max(0.02, b.intro_open))
    b.arrive = min(1.0, max(0.1, b.arrive))
    b.outro = max(0.0, b.outro) or 1.0


control_values, apply_control, controls_payload = bind_controls(
    CONTROLS, reconcile)
