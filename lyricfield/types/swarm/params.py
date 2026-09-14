"""Swarm's tunables: words fly in, settle, and get knocked apart.

A physical renderer, and deliberately not a physical *simulation*. Bullet and
the Particle SOP step per cook, so a dropped frame or a seek changes what they
produce and the same song renders differently twice. Here the integrator is
twenty lines of numpy re-run from the line's own start on every frame, which
costs almost nothing for a handful of words and makes a frame a pure function
of its timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .._controls import Control, bind_controls


@dataclass
class Frame:
    width: int = 720
    height: int = 1280


@dataclass
class Flight:
    """How a word arrives and comes to rest."""

    # How far from its resting place a word starts, as a share of the frame.
    throw: float = 0.3
    # The spring that pulls it home, and the drag that stops it overshooting
    # forever. Together these are the whole feel of the thing.
    stiff: float = 74.0
    damp: float = 9.5
    # Words do not all arrive at once; each is delayed by this much more than
    # the one before.
    stagger: float = 0.02


@dataclass
class Burst:
    """What a kick does to a settled line."""

    push: float = 3.0       # impulse away from the centre
    spin: float = 1.1        # ... and a little sideways, so it is not radial


@dataclass
class Line:
    font: str = "Arial"
    size: float = 66.0
    lead: float = 0.35
    hold: float = 1.0
    fade: float = 0.45
    gap: float = 0.085       # vertical space between rows, share of the frame
    per_row: int = 3         # words to a row


@dataclass
class Look:
    hue: float = 0.02
    sat: float = 0.45
    peak: float = 0.95
    floor: float = 0.02
    glow: float = 0.2
    bloom: float = 13.0


@dataclass
class Beat:
    intro_open: float = 0.35
    arrive: float = 0.85
    outro: float = 11.0


@dataclass
class Params:
    frame: Frame = field(default_factory=Frame)
    flight: Flight = field(default_factory=Flight)
    burst: Burst = field(default_factory=Burst)
    line: Line = field(default_factory=Line)
    look: Look = field(default_factory=Look)
    beat: Beat = field(default_factory=Beat)

    def validate(self) -> list[str]:
        out: list[str] = []
        f, fl, bu, ln, lk, b = (self.frame, self.flight, self.burst, self.line,
                                self.look, self.beat)
        if fl.stiff <= 0:
            out.append("stiff must be positive, or a word never comes home")
        if fl.damp < 0:
            out.append("damp cannot be negative")
        # Underdamped is the point -- a word should overshoot slightly -- but
        # past the critical value it rings forever and never settles.
        if fl.damp > 2.0 * (fl.stiff ** 0.5) * 1.4:
            out.append(
                f"damp {fl.damp} is so far past critical for stiff {fl.stiff} "
                "that words crawl home instead of arriving")
        if fl.throw < 0:
            out.append("throw cannot be negative")
        if ln.per_row < 1:
            out.append("per_row must be at least one word")
        if ln.size <= 0:
            out.append("size must be positive; it is a font size")
        if not (0.0 < ln.gap < 0.6):
            out.append(f"gap {ln.gap} is not a usable row spacing")
        if lk.floor >= lk.peak:
            out.append("floor must be below peak")
        if b.outro <= 0:
            out.append("outro must be positive; it is the length of the ending")
        if not (0.0 < b.intro_open <= 1.0):
            out.append(f"intro_open {b.intro_open} must be above 0 and at most 1")
        if not (0.0 < b.arrive <= 1.0):
            out.append(f"arrive {b.arrive} must be above 0 and at most 1")
        return out


RANGES: dict[str, tuple] = {
    "width": (240, 2160, 2), "height": (240, 3840, 2),
    "throw": (0.0, 2.0, 0.01), "stiff": (1.0, 200.0, 0.5),
    "damp": (0.0, 40.0, 0.1), "stagger": (0.0, 0.5, 0.01),
    "push": (0.0, 6.0, 0.05), "spin": (-3.0, 3.0, 0.05),
    "size": (8, 200, 1), "lead": (0.0, 3.0, 0.05),
    "hold": (0.05, 5.0, 0.05), "fade": (0.02, 3.0, 0.01),
    "gap": (0.01, 0.5, 0.005), "per_row": (1, 8, 1),
    "hue": (0, 1, 0.01), "sat": (0, 1, 0.01),
    "peak": (0.2, 1.0, 0.01), "floor": (0.0, 0.3, 0.005),
    "glow": (0, 1, 0.01), "bloom": (0, 60, 1),
    "intro_open": (0.02, 1.0, 0.01), "arrive": (0.1, 1.0, 0.01),
    "outro": (0, 60, 1),
}


CONTROLS: tuple[Control, ...] = (
    Control("arrival", "Arrival",
            "How far the words come from and how staggered their entrance is.",
            "flight.throw", {"flight.throw": (0.12, 1.1),
                             "flight.stagger": (0.0, 0.16)}),
    Control("spring", "Spring",
            "How sharply a word snaps into place, from a drift to a whip.",
            "flight.stiff", {"flight.stiff": (8.0, 90.0),
                             "flight.damp": (3.0, 11.0)}),
    Control("kick", "Kick",
            "How hard a kick knocks the settled line apart.",
            "burst.push", {"burst.push": (0.0, 3.4),
                           "burst.spin": (0.0, 1.4)}),
    Control("glow", "Glow",
            "The halo around the type, and how far it spreads.",
            "look.glow", {"look.glow": (0.05, 0.6),
                          "look.bloom": (4.0, 32.0)}),
)


def reconcile(params: "Params") -> None:
    f, fl, bu, ln, lk, b = (params.frame, params.flight, params.burst,
                            params.line, params.look, params.beat)
    fl.stiff = max(0.5, fl.stiff)
    fl.damp = max(0.0, fl.damp)
    # Keep it this side of a crawl; overshoot is wanted, treacle is not.
    fl.damp = min(fl.damp, 2.0 * (fl.stiff ** 0.5) * 1.4)
    fl.throw = max(0.0, fl.throw)
    ln.per_row = max(1, int(ln.per_row))
    ln.size = max(1.0, ln.size)
    ln.gap = min(0.55, max(0.011, ln.gap))
    lk.floor = min(lk.floor, max(0.0, lk.peak - 0.005))
    b.intro_open = min(1.0, max(0.02, b.intro_open))
    b.arrive = min(1.0, max(0.1, b.arrive))
    b.outro = max(0.0, b.outro) or 1.0


control_values, apply_control, controls_payload = bind_controls(
    CONTROLS, reconcile)
