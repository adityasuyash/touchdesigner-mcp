"""Longhand's tunables: a camera travelling a written line.

From the Chainsmokers' "Closer" lyric video. The first reading of that
reference was wrong -- `approach` flew words at the camera through depth slabs
-- and the right one is a camera panning along one long handwritten string of
the lyrics, word to word.

So the vocabulary is a path and a camera: how the line meanders, how far ahead
and behind you can see, and how the camera eases from word to word. There is no
grid, no glyph ramp, and nothing that arrives instantly.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .._controls import Control, bind_controls


@dataclass
class Stage:
    """The frame, and the hand the words are written in."""

    width: int = 720
    height: int = 1280
    # A script face is most of the look. Bradley Hand is casual and legible at
    # size; Snell Roundhand is the formal one.
    font: str = "Bradley Hand"
    size: float = 86.0
    # Where the word being sung sits in the frame, 0 left to 1 right. Slightly
    # left of centre reads as a camera leading the line rather than centring it.
    focus_x: float = 0.44
    focus_y: float = 0.5


@dataclass
class Line:
    """How the written line is laid out in the space the camera moves through."""

    # Space between words, in multiples of a space's width.
    gap: float = 1.6
    # How far the line wanders from the horizontal, as a share of frame height.
    meander: float = 0.16
    # How many words one full wander takes. Long, or it reads as a wave rather
    # than as handwriting that is not quite straight.
    wander_words: float = 7.0
    # A second, slower wander on top, so the path does not repeat visibly.
    drift_words: float = 23.0
    # A gentle tilt to each word, the way a hand-written line does not sit
    # perfectly level. Degrees at the extremes.
    tilt: float = 3.5


@dataclass
class Camera:
    """How the eye travels the line. Never in a hurry, never quite still."""

    # How much of the journey to the next word is spent moving, as a multiple
    # of the gap between cues. Above 1 the camera is still travelling when the
    # next word lands, which is what keeps it always in motion.
    chase: float = 1.35
    # How far the camera drifts on its own, as a share of frame height.
    float_: float = 0.035
    # Seconds for one full drift. Slow enough to read as floating rather than
    # as a wobble.
    float_secs: float = 7.0
    # Scale: the line breathes toward and away from the camera.
    breathe: float = 0.05


@dataclass
class Look:
    hue: float = 0.09
    sat: float = 0.10
    # The word being sung, and the ones either side of it.
    peak: float = 0.93
    # How quickly a word dims with distance from the focus, per word.
    falloff: float = 0.42
    # Faintest a word may be drawn before it is not worth drawing.
    floor: float = 0.03
    # How many words either side to draw at all. Past this they are invisible
    # and cost a Spec DAT row each.
    reach: int = 7
    glow: float = 0.34
    bloom: float = 18.0


@dataclass
class Beat:
    """What the drums do inside this renderer, as opposed to the response
    chain that sits after every renderer."""

    kick_lift: float = 0.06
    kick_time: float = 0.25
    intro_open: float = 0.35
    arrive: float = 0.88
    outro: float = 10.0


@dataclass
class Params:
    stage: Stage = field(default_factory=Stage)
    line: Line = field(default_factory=Line)
    camera: Camera = field(default_factory=Camera)
    look: Look = field(default_factory=Look)
    beat: Beat = field(default_factory=Beat)

    def validate(self) -> list[str]:
        out: list[str] = []
        s, ln, cam, lk, b = (self.stage, self.line, self.camera, self.look,
                             self.beat)
        if s.size <= 0:
            out.append("size must be positive; it is a font size")
        for name, v in (("focus_x", s.focus_x), ("focus_y", s.focus_y)):
            if not (0.0 <= v <= 1.0):
                out.append(f"{name} {v} is outside the frame")
        if ln.gap <= 0:
            out.append("gap must be positive, or the words sit on top of each other")
        if ln.wander_words <= 1:
            out.append(
                f"wander_words {ln.wander_words} makes the line zigzag word to "
                "word rather than wander")
        if ln.drift_words <= ln.wander_words:
            out.append(
                "drift_words must be longer than wander_words, or the two "
                "wanders beat against each other into a regular pattern")
        if cam.chase <= 0:
            out.append("chase must be positive; it is a travel time")
        if cam.chase < 1.0:
            out.append(
                f"chase {cam.chase} lands the camera before the next word is "
                "sung, so it stops between words and reads as a slideshow")
        if cam.float_secs <= 0:
            out.append("float_secs must be positive; it is a period")
        if lk.reach < 1:
            out.append("reach must be at least 1, or only the sung word is drawn")
        if lk.falloff <= 0:
            out.append("falloff must be positive; it is a dimming per word")
        if lk.floor >= lk.peak:
            out.append("floor must be below peak")
        # Brightness stacks at the output: the ground is added to the type and
        # the bloom goes on with `maximum`.
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
        """The band the line travels through. Not `band`/`lower`, which mean
        "inside the character grid" and there is no grid here."""
        s, ln = self.stage, self.line
        h = int(s.height * (0.22 + ln.meander * 2))
        y = int(max(0, min(s.height - h, s.height * s.focus_y - h / 2)))
        return {"line": (0, y, s.width, h)}


RANGES: dict[str, tuple] = {
    "width": (240, 2160, 2), "height": (240, 3840, 2),
    "size": (20.0, 300.0, 1.0),
    "focus_x": (0.0, 1.0, 0.01), "focus_y": (0.0, 1.0, 0.01),
    "gap": (0.2, 6.0, 0.1), "meander": (0.0, 0.5, 0.01),
    "wander_words": (1.5, 40.0, 0.5), "drift_words": (2.0, 120.0, 1.0),
    "tilt": (0.0, 20.0, 0.5),
    "chase": (1.0, 4.0, 0.05), "float_": (0.0, 0.2, 0.005),
    "float_secs": (1.0, 30.0, 0.5), "breathe": (0.0, 0.4, 0.005),
    "hue": (0, 1, 0.01), "sat": (0, 1, 0.01),
    "peak": (0.2, 1.0, 0.01), "falloff": (0.05, 2.0, 0.01),
    "floor": (0.0, 0.5, 0.005), "reach": (1, 20, 1),
    "glow": (0, 1, 0.01), "bloom": (0, 60, 1),
    "kick_lift": (0.0, 0.4, 0.01), "kick_time": (0.05, 2.0, 0.05),
    "intro_open": (0.02, 1.0, 0.01), "arrive": (0.1, 1.0, 0.01),
    "outro": (0, 60, 1),
}


CONTROLS: tuple[Control, ...] = (
    Control("hand", "Hand",
            "How large the writing is, and how far apart the words sit.",
            "stage.size", {"stage.size": (52.0, 130.0),
                           "line.gap": (1.1, 2.2)}),
    Control("wander", "Wander",
            "How far the written line strays from level.",
            "line.meander", {"line.meander": (0.02, 0.32),
                             "line.tilt": (0.5, 9.0)}),
    Control("travel", "Travel",
            "How long the camera takes to reach each word.",
            "camera.chase", {"camera.chase": (1.02, 2.4)}),
    Control("depth", "Depth",
            "How much of the line either side of the word stays visible.",
            "look.falloff", {"look.falloff": (0.9, 0.16),
                             "look.reach": (3, 14)}),
)


def reconcile(params: "Params") -> None:
    """Settle the relationships `validate()` insists on."""
    s, ln, cam, lk, b = (params.stage, params.line, params.camera, params.look,
                         params.beat)
    s.size = max(1.0, s.size)
    s.focus_x = min(1.0, max(0.0, s.focus_x))
    s.focus_y = min(1.0, max(0.0, s.focus_y))
    ln.gap = max(0.05, ln.gap)
    ln.wander_words = max(1.5, ln.wander_words)
    ln.drift_words = max(ln.wander_words * 1.5, ln.drift_words)
    # Never below 1: a camera that arrives early stops, and a camera that stops
    # between words is a slideshow. This is the whole feel of the reference.
    cam.chase = max(1.0, cam.chase)
    cam.float_secs = max(0.5, cam.float_secs)
    lk.reach = max(1, int(lk.reach))
    lk.falloff = max(0.01, lk.falloff)
    lk.floor = min(lk.floor, max(0.0, lk.peak - 0.01))
    # In order of what may give way: the kick's lift of the ground, then the
    # ground. The writing's own brightness is legibility and stays.
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
