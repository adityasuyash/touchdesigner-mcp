"""Monument's tunables: one word, as large as it will go.

Nothing here is shared with `lyric_grid`. That is deliberate and it is the
point of the type: importing `Grid` is what made two other renderers draw the
same character field, so this one has no `cols`, no `vrows`, no `band` and no
glyph ramp. It has a frame, a word, and how that word arrives and leaves.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .._controls import Control, bind_controls


@dataclass
class Stage:
    """The frame, and how much of it a word is allowed to fill."""

    width: int = 720
    height: int = 1280
    font: str = "Arial"
    # A word is scaled to this share of the frame's width. It is the whole look:
    # at 0.9 the type is a wall, at 0.4 it is a caption.
    fill: float = 0.93
    # ... but never past this, or a two-letter word ("I", "a") becomes a
    # texture rather than a word.
    cap_px: float = 340.0
    # Where the word sits vertically, 0 at the top and 1 at the bottom.
    line_y: float = 0.5


@dataclass
class Word:
    """How a word arrives, holds and leaves."""

    # Scale at the instant it lands, falling to 1.0 over `settle`. This is what
    # makes it read as struck rather than faded in.
    punch: float = 1.34
    settle: float = 0.12
    # Seconds a word stays up after its cue, and how long it takes to go. A
    # word with no successor leans on these alone.
    hold: float = 0.4
    fade: float = 0.16
    # The word before, still on screen behind this one.
    ghost: float = 0.1
    ghost_scale: float = 1.75
    # Vertical travel across a word's life, as a share of frame height.
    drift: float = 0.01


@dataclass
class Look:
    hue: float = 0.0
    sat: float = 0.0
    # Peak brightness of a lit word, and of the ground it sits on.
    peak: float = 0.88
    floor: float = 0.02
    glow: float = 0.16
    bloom: float = 7.0


@dataclass
class Beat:
    """What the drums do to a picture whose subject is a word."""

    # The ground lifts on a kick rather than the word moving: the word belongs
    # to the cue table, the room belongs to the beat.
    kick_lift: float = 0.05
    kick_time: float = 0.20
    # Where in the song this is.
    intro_open: float = 0.35
    arrive: float = 0.85
    outro: float = 10.0


@dataclass
class Params:
    stage: Stage = field(default_factory=Stage)
    word: Word = field(default_factory=Word)
    look: Look = field(default_factory=Look)
    beat: Beat = field(default_factory=Beat)

    def validate(self) -> list[str]:
        out: list[str] = []
        s, w, lk, b = self.stage, self.word, self.look, self.beat
        if not (0.0 < s.fill <= 1.0):
            out.append(f"fill {s.fill} must be above 0 and at most 1")
        if s.cap_px <= 0:
            out.append("cap_px must be positive; it is a font size")
        if not (0.0 <= s.line_y <= 1.0):
            out.append(f"line_y {s.line_y} is outside the frame")
        if w.punch < 1.0:
            out.append(f"punch {w.punch} would shrink a word as it lands")
        if w.ghost_scale < 1.0:
            out.append("ghost_scale below 1 puts the ghost in front")
        if w.ghost >= lk.peak:
            out.append(
                f"ghost {w.ghost} is as bright as the word itself ({lk.peak})")
        if lk.floor >= lk.peak:
            out.append("floor must be below peak")
        # Brightness stacks, and the rule has to describe THIS network rather
        # than be copied from the grid's. Here the ground is composited onto
        # the type with `add`, so those two sum; the bloom goes on with
        # `maximum`, so it cannot push past the type it was blurred from.
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
        """A word is drawn in the middle band; the edges should stay dark.

        Not the `band`/`lower` pair the grid types declare -- those names mean
        "inside the character band" and this renderer has no band.
        """
        s = self.stage
        h = int(s.height * 0.46)
        y = int(max(0, min(s.height - h, s.height * s.line_y - h / 2)))
        return {"word": (0, y, s.width, h)}


RANGES: dict[str, tuple] = {
    "width": (240, 2160, 2), "height": (240, 3840, 2),
    "fill": (0.2, 1.0, 0.01), "cap_px": (40, 900, 5),
    "line_y": (0.0, 1.0, 0.01),
    "punch": (1.0, 2.0, 0.01), "settle": (0.02, 2.0, 0.01),
    "hold": (0.05, 4.0, 0.05), "fade": (0.02, 3.0, 0.01),
    "ghost": (0.0, 0.8, 0.01), "ghost_scale": (1.0, 3.0, 0.05),
    "drift": (0.0, 0.3, 0.005),
    "hue": (0, 1, 0.01), "sat": (0, 1, 0.01),
    "peak": (0.2, 1.0, 0.01), "floor": (0.0, 0.3, 0.005),
    "glow": (0, 1, 0.01), "bloom": (0, 60, 1),
    "kick_lift": (0.0, 0.6, 0.01), "kick_time": (0.05, 2.0, 0.05),
    "intro_open": (0.02, 1.0, 0.01), "arrive": (0.1, 1.0, 0.01),
    "outro": (0, 60, 1),
}


CONTROLS: tuple[Control, ...] = (
    Control("size", "Size",
            "How much of the frame one word fills, from a caption to a wall.",
            "stage.fill", {"stage.fill": (0.45, 0.95),
                           "stage.cap_px": (170.0, 380.0)}),
    Control("impact", "Impact",
            "How hard a word lands: the scale it arrives at and how quickly "
            "it settles.",
            "word.punch", {"word.punch": (1.0, 1.45),
                           "word.settle": (0.4, 0.1)}),
    Control("afterimage", "Afterimage",
            "How much of the word before is still on screen behind this one.",
            "word.ghost", {"word.ghost": (0.0, 0.42),
                           "word.ghost_scale": (1.15, 1.9)}),
    Control("glow", "Glow",
            "The halo around the type, and how far it spreads.",
            "look.glow", {"look.glow": (0.06, 0.6),
                          "look.bloom": (4.0, 34.0)}),
)


def reconcile(params: "Params") -> None:
    """Settle the relationships `validate()` insists on."""
    s, w, lk, b = params.stage, params.word, params.look, params.beat
    s.fill = min(1.0, max(0.05, s.fill))
    s.cap_px = max(10.0, s.cap_px)
    s.line_y = min(1.0, max(0.0, s.line_y))
    w.punch = max(1.0, w.punch)
    w.ghost_scale = max(1.0, w.ghost_scale)
    lk.floor = min(lk.floor, lk.peak - 0.01)
    w.ghost = min(w.ghost, max(0.0, lk.peak - 0.02))
    # Keep the stack under white by giving way on the kick's lift of the
    # ground: that is a matter of taste, where the word's own brightness is a
    # matter of legibility and must stay where it was asked to be.
    # In order of what may give way: the kick's lift of the ground first, then
    # the ground itself. Both are matters of taste. The word's own brightness
    # is a matter of legibility and stays where it was asked to be.
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
