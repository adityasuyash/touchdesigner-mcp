"""Window's tunables: the words are a hole, the light is behind them.

The only renderer here where the two halves of this system share one picture.
Everywhere else a song is either words (lyric) or beat (beatsync); this one
draws a moving beat-driven field and lets the lyrics cut it out, so what you
read is type and what you see move is the drums.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .._controls import Control, bind_controls


@dataclass
class Frame:
    width: int = 720
    height: int = 1280
    # The field is computed at this share of the frame and scaled up. It is
    # soft by construction, so nobody can tell and it costs a quarter as much.
    scale: float = 0.5


@dataclass
class Line:
    """The lyrics, as a line at a time rather than a word at a time."""

    font: str = "Arial"
    size: float = 112.0
    # A line appears this long before its first word and stays this long after
    # its last, so reading it is never a race.
    lead: float = 0.35
    hold: float = 0.9
    fade: float = 0.45
    line_y: float = 0.5
    wrap: int = 12          # characters before the line breaks


@dataclass
class Field:
    """What moves behind the letters."""

    bands: float = 4.5       # horizontal bands across the frame
    drift: float = 0.45      # how fast they travel, frame-heights a second
    warp: float = 0.35       # how much the bands bend
    kick_push: float = 0.38  # a kick shoves the whole field
    kick_time: float = 0.35
    hat_grain: float = 0.18
    hat_time: float = 0.18


@dataclass
class Look:
    hue: float = 0.52
    sat: float = 0.5
    # How bright the light behind the letters gets, and the dark it sits in.
    peak: float = 0.92
    floor: float = 0.03
    glow: float = 0.26
    bloom: float = 16.0


@dataclass
class Beat:
    intro_open: float = 0.35
    arrive: float = 0.85
    outro: float = 11.0


@dataclass
class Params:
    frame: Frame = field(default_factory=Frame)
    line: Line = field(default_factory=Line)
    field_: Field = field(default_factory=Field)
    look: Look = field(default_factory=Look)
    beat: Beat = field(default_factory=Beat)

    def validate(self) -> list[str]:
        out: list[str] = []
        f, ln, fl, lk, b = (self.frame, self.line, self.field_, self.look,
                            self.beat)
        if not (0.1 <= f.scale <= 1.0):
            out.append(f"scale {f.scale} must be between 0.1 and 1")
        if ln.size <= 0:
            out.append("size must be positive; it is a font size")
        if ln.wrap < 4:
            out.append("wrap below four characters cannot hold a word")
        if not (0.0 <= ln.line_y <= 1.0):
            out.append(f"line_y {ln.line_y} is outside the frame")
        if fl.bands <= 0:
            out.append("bands must be positive; it is how many cross the frame")
        if lk.floor >= lk.peak:
            out.append("floor must be below peak")
        # The field is what shows through the letters, so its own stack is what
        # must stay under white; the matte cannot brighten anything.
        stacked = lk.peak + fl.kick_push * 0.5 + fl.hat_grain
        if stacked > 1.3:
            out.append(
                f"peak {lk.peak} with a kick at {fl.kick_push} and hats at "
                f"{fl.hat_grain} reaches ~{stacked:.2f}")
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
    "size": (12, 300, 1), "lead": (0.0, 3.0, 0.05),
    "hold": (0.05, 5.0, 0.05), "fade": (0.02, 3.0, 0.01),
    "line_y": (0.0, 1.0, 0.01), "wrap": (4, 60, 1),
    "bands": (0.5, 40.0, 0.5), "drift": (-2.0, 2.0, 0.01),
    "warp": (0.0, 2.0, 0.01),
    "kick_push": (0.0, 1.0, 0.01), "kick_time": (0.05, 3.0, 0.05),
    "hat_grain": (0.0, 0.8, 0.01), "hat_time": (0.05, 2.0, 0.05),
    "hue": (0, 1, 0.01), "sat": (0, 1, 0.01),
    "peak": (0.2, 1.0, 0.01), "floor": (0.0, 0.3, 0.005),
    "glow": (0, 1, 0.01), "bloom": (0, 60, 1),
    "intro_open": (0.02, 1.0, 0.01), "arrive": (0.1, 1.0, 0.01),
    "outro": (0, 60, 1),
}


CONTROLS: tuple[Control, ...] = (
    Control("reading", "Reading size",
            "How large the lyrics are set, and how many characters fit on a "
            "line before it breaks.",
            "line.size", {"line.size": (44.0, 120.0),
                          "line.wrap": (26, 12)}),
    Control("current", "Current",
            "How fast the light behind the letters travels, and how much it "
            "bends.",
            "field_.drift", {"field_.drift": (0.03, 0.6),
                             "field_.warp": (0.05, 0.9)}),
    Control("push", "Push",
            "How hard a kick shoves the whole field.",
            "field_.kick_push", {"field_.kick_push": (0.0, 0.85),
                                 "field_.kick_time": (0.15, 0.7)}),
    Control("glow", "Glow",
            "The halo the letters throw, and how far it spreads.",
            "look.glow", {"look.glow": (0.04, 0.6),
                          "look.bloom": (4.0, 36.0)}),
)


def reconcile(params: "Params") -> None:
    """Settle the relationships `validate()` insists on."""
    f, ln, fl, lk, b = (params.frame, params.line, params.field_, params.look,
                        params.beat)
    f.scale = min(1.0, max(0.1, f.scale))
    ln.size = max(1.0, ln.size)
    ln.wrap = max(4, int(ln.wrap))
    ln.line_y = min(1.0, max(0.0, ln.line_y))
    fl.bands = max(0.1, fl.bands)
    lk.floor = min(lk.floor, max(0.0, lk.peak - 0.005))
    # The kick gives way first: it is the loudest term and the one most likely
    # to have been pushed. The light behind the letters is what is being read
    # through, so it keeps its brightness.
    # In order of what may give way: the kick's shove, then the hi-hat grain.
    # The light itself is what is being read through and keeps its brightness.
    over = (lk.peak + fl.kick_push * 0.5 + fl.hat_grain) - 1.3
    if over > 0:
        give = min(over, fl.kick_push * 0.5)
        fl.kick_push, over = fl.kick_push - give * 2.0, over - give
    if over > 0:
        fl.hat_grain = max(0.0, fl.hat_grain - over)
    b.intro_open = min(1.0, max(0.02, b.intro_open))
    b.arrive = min(1.0, max(0.1, b.arrive))
    b.outro = max(0.0, b.outro) or 1.0


control_values, apply_control, controls_payload = bind_controls(
    CONTROLS, reconcile)
