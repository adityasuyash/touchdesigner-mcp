"""Longhand's tunables: handwritten words in a volume, and a camera in it too.

From the Chainsmokers' "Closer" lyric video. The reference has been read wrong
twice here. `approach` flew words at the camera down a tunnel; `longhand` then
panned along one flat written line. What the sources actually describe is both
halves at once -- PremiumBeat, on that video: "live action footage compiled
with lyrics that fly through 3d space", over a practical effect that began as
text written on paper and filmed. Handwriting, and depth, and the motion blur
of a camera moving among it.

The live-action half is out of reach -- nothing in this pipeline takes a video
input -- so the ground stays dark. The type half is what makes the video
recognisable and it is reachable.

So the vocabulary is a volume and a camera inside it: where words sit, how the
eye wanders between them, and how distance costs size, light and focus. There
is no grid, no glyph ramp, and no line to follow.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .._controls import Control, bind_controls


@dataclass
class Stage:
    """The frame, the hand the words are written in, and the lens."""

    width: int = 720
    height: int = 1280
    # A script face is most of the look. Bradley Hand is casual and legible at
    # size; Snell Roundhand is the formal one.
    font: str = "Bradley Hand"
    # Font size in pixels at depth 1.0. Every other size follows from this and
    # the depth a word is at, so it is the one number that sets the scale.
    size_at_one: float = 260.0
    # Where the camera's axis sits in the frame, 0..1. Off centre reads as
    # someone looking through a space rather than as a tunnel pointed at you.
    focus_x: float = 0.46
    focus_y: float = 0.52


@dataclass
class Volume:
    """Where the words are. Fixed once, and then only the camera moves.

    Positions are a pure function of the word's index -- no RNG -- so a
    re-render is identical, which is the rule CLAUDE.md sets for anything with
    a choice. Everything is in depth units, where 1.0 is "as wide as the
    frame at depth 1".
    """

    # How far words stray from the camera's axis, sideways and vertically.
    # Wide enough that consecutive words are not stacked, narrow enough that
    # the camera does not have to swing to find the next one.
    spread_x: float = 1.00
    spread_y: float = 0.62
    # The near and far walls. A word is not drawn outside them.
    near_z: float = 0.35
    far_z: float = 5.00
    # How far the volume advances per word, so the lyrics run away from the
    # camera rather than piling up in one room. The camera follows, so this is
    # the sense of travel rather than a speed.
    march: float = 0.62
    # How many words either side of the sung one are placed at all. Past this
    # they are behind the camera or past the far wall and cost a row each.
    reach: int = 9


@dataclass
class Camera:
    """How the eye moves through the volume. Never in a hurry, never still."""

    # How much of the journey to the next word is spent moving, as a multiple
    # of the gap between cues. Above 1 the camera is still travelling when the
    # next word lands, which is what keeps it floating rather than reading as
    # a slideshow. This is the single most load-bearing number here.
    chase: float = 1.35
    # How far back from the word it is chasing the camera settles, in depth.
    # It has to be more than `march` past `near_z`, or the word just sung is
    # already behind the camera and nothing ever sweeps past: measured at 0.85
    # against a march of 0.62, every frame held only words yet to come, which
    # reads as a queue rather than as travelling through anything.
    standoff: float = 1.55
    # The wander on top of the chase, as a share of the spread, and the slowest
    # of its three periods in seconds. Three incommensurable sines, so it never
    # visibly repeats; see `beat.drift`, which this mirrors.
    float_: float = 0.22
    float_secs: float = 11.0


@dataclass
class Depth:
    """The slabs the space is quantised into.

    A Text TOP has ONE font size for its whole Specification DAT, so continuous
    perspective is not available: the space is cut into `layers` slabs, each
    its own Text TOP at its own fixed size, and a word is drawn by whichever
    slab is nearest its depth. More slabs is smoother travel and more
    operators.
    """

    layers: int = 5
    # Brightness of the farthest slab relative to the nearest. This is the fog,
    # and it is what makes the depth read at all.
    fog: float = 0.30
    # Blur on the farthest slab, in pixels, tapering to none at the nearest:
    # distance should cost focus as well as size and light.
    haze: float = 3.5


@dataclass
class Blur:
    """The motion blur. The third thing every breakdown of that video names.

    Three taps of the whole layer offset along the camera's screen-space
    velocity and averaged, rather than a directional-blur operator: it is a
    pure function of the timestamp, it uses only operators this project has
    already proved, and it costs two transforms.
    """

    # How far the taps are thrown, as a MULTIPLE of how far the frame moved in
    # the last frame's worth of time -- 1.0 smears exactly the distance the
    # camera travelled. Not a distance in pixels: an absolute smear is the same
    # whether the camera is racing or almost still, which reads as a soft
    # render rather than as movement. Zero switches the whole branch off.
    amount: float = 0.6
    # The most it may smear, whatever the camera does. A cut-sized jump would
    # otherwise wash the frame out entirely.
    ceiling: float = 40.0


@dataclass
class Look:
    hue: float = 0.09
    sat: float = 0.10
    # The word being sung.
    peak: float = 0.93
    # Faintest a word may be drawn before it is not worth a row.
    floor: float = 0.03
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
    volume: Volume = field(default_factory=Volume)
    camera: Camera = field(default_factory=Camera)
    depth: Depth = field(default_factory=Depth)
    blur: Blur = field(default_factory=Blur)
    look: Look = field(default_factory=Look)
    beat: Beat = field(default_factory=Beat)

    def validate(self) -> list[str]:
        out: list[str] = []
        s, v, cam = self.stage, self.volume, self.camera
        d, bl, lk, b = self.depth, self.blur, self.look, self.beat

        if s.size_at_one <= 0:
            out.append("size_at_one must be positive; it is a font size")
        for name, val in (("focus_x", s.focus_x), ("focus_y", s.focus_y)):
            if not (0.0 <= val <= 1.0):
                out.append(f"{name} {val} is outside the frame")

        if v.near_z <= 0:
            out.append(
                f"near_z {v.near_z} is at or behind the camera, where a "
                "perspective divide has no answer")
        if v.far_z <= v.near_z:
            out.append("far_z must be beyond near_z; they are the two walls")
        if v.spread_x <= 0 or v.spread_y <= 0:
            out.append("a spread of zero stacks every word on the axis")
        if v.march <= 0:
            out.append(
                "march must be positive, or the lyrics never leave the room "
                "the first word is in")
        if v.reach < 1:
            out.append("reach must be at least 1, or only the sung word is drawn")

        if cam.chase <= 0:
            out.append("chase must be positive; it is a travel time")
        if cam.chase < 1.0:
            out.append(
                f"chase {cam.chase} lands the camera before the next word is "
                "sung, so it stops between words and reads as a slideshow")
        if cam.standoff <= 0:
            out.append(
                "standoff must be positive, or the camera arrives inside the "
                "word it is looking at")
        if cam.standoff < v.near_z:
            out.append(
                f"standoff {cam.standoff} is closer than near_z {v.near_z}, so "
                "the word being sung is clipped at the moment it is sung")
        if cam.float_secs <= 0:
            out.append("float_secs must be positive; it is a period")

        if d.layers < 2:
            out.append(
                f"layers {d.layers} gives every word one size, which is a flat "
                "line rather than a volume")
        if not (0.0 <= d.fog <= 1.0):
            out.append(f"fog {d.fog} is a relative brightness, 0 to 1")
        if d.haze < 0:
            out.append("haze is a blur radius and cannot be negative")

        if bl.amount < 0 or bl.ceiling < 0:
            out.append("a blur distance cannot be negative")
        if bl.amount > 0 and bl.ceiling <= 0:
            out.append(
                "ceiling is the most the smear may reach in pixels; at zero "
                "the branch is built and then never allowed to do anything")

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
        """The part of the frame the words move through.

        Nearly all of it: a volume has no band. Not `band`/`lower`, which mean
        "inside the character grid" and there is no grid here.
        """
        s = self.stage
        return {"volume": (0, int(s.height * 0.08), s.width,
                           int(s.height * 0.84))}


def slab_depths(params: "Params") -> list[float]:
    """The depth each slab stands at, nearest first.

    Geometric rather than even, because apparent size goes as 1/z: evenly
    spaced slabs put four of five of them in the far half of the volume, where
    the difference between them is a pixel or two. The field script assigns
    each word to a slab from this same list, so the two cannot disagree about
    what size a given depth is drawn at -- which would make the perspective
    simply wrong with nothing on screen to show for it.
    """
    v, n = params.volume, max(2, int(params.depth.layers))
    near, far = max(1e-3, v.near_z), max(v.near_z * 1.01, v.far_z)
    ratio = (far / near) ** (1.0 / (n - 1))
    return [round(near * ratio ** i, 4) for i in range(n)]


RANGES: dict[str, tuple] = {
    "width": (240, 2160, 2), "height": (240, 3840, 2),
    "size_at_one": (40.0, 400.0, 1.0),
    "focus_x": (0.0, 1.0, 0.01), "focus_y": (0.0, 1.0, 0.01),
    "spread_x": (0.1, 3.0, 0.05), "spread_y": (0.05, 2.0, 0.05),
    "near_z": (0.1, 2.0, 0.05), "far_z": (0.5, 12.0, 0.1),
    "march": (0.05, 3.0, 0.01), "reach": (1, 24, 1),
    "chase": (1.0, 4.0, 0.05), "standoff": (0.1, 3.0, 0.05),
    "float_": (0.0, 1.0, 0.01), "float_secs": (1.0, 40.0, 0.5),
    "layers": (2, 8, 1), "fog": (0.0, 1.0, 0.01), "haze": (0.0, 20.0, 0.5),
    "amount": (0.0, 60.0, 0.5), "ceiling": (0.0, 160.0, 1.0),
    "hue": (0, 1, 0.01), "sat": (0, 1, 0.01),
    "peak": (0.2, 1.0, 0.01), "floor": (0.0, 0.5, 0.005),
    "glow": (0, 1, 0.01), "bloom": (0, 60, 1),
    "kick_lift": (0.0, 0.4, 0.01), "kick_time": (0.05, 2.0, 0.05),
    "intro_open": (0.02, 1.0, 0.01), "arrive": (0.1, 1.0, 0.01),
    "outro": (0, 60, 1),
}


CONTROLS: tuple[Control, ...] = (
    Control("hand", "Hand",
            "How large the writing is.",
            "stage.size_at_one", {"stage.size_at_one": (150.0, 360.0)}),
    Control("scatter", "Scatter",
            "How far the words stray from the camera's path.",
            "volume.spread_x", {"volume.spread_x": (0.35, 2.2),
                                "volume.spread_y": (0.2, 1.3)}),
    Control("travel", "Travel",
            "How long the camera takes to reach each word.",
            "camera.chase", {"camera.chase": (1.02, 2.4)}),
    Control("depth", "Depth",
            "How far into the distance the lyrics run.",
            "volume.far_z", {"volume.far_z": (1.6, 7.0),
                             "volume.march": (0.25, 1.4),
                             "depth.fog": (0.6, 0.12)}),
    Control("smear", "Smear",
            "How much the writing blurs as the camera moves.",
            "blur.amount", {"blur.amount": (0.0, 1.8)}),
)


def reconcile(params: "Params") -> None:
    """Settle the relationships `validate()` insists on."""
    s, v, cam = params.stage, params.volume, params.camera
    d, bl, lk, b = params.depth, params.blur, params.look, params.beat

    s.size_at_one = max(1.0, s.size_at_one)
    s.focus_x = min(1.0, max(0.0, s.focus_x))
    s.focus_y = min(1.0, max(0.0, s.focus_y))

    v.near_z = max(0.05, v.near_z)
    v.far_z = max(v.near_z * 1.2, v.far_z)
    v.spread_x = max(0.01, v.spread_x)
    v.spread_y = max(0.01, v.spread_y)
    v.march = max(0.01, v.march)
    v.reach = max(1, int(v.reach))

    # Never below 1: a camera that arrives early stops, and a camera that stops
    # between words is a slideshow. This is the whole feel of the reference.
    cam.chase = max(1.0, cam.chase)
    # At least the near wall, or the word being sung is clipped exactly when it
    # is sung -- the one frame the renderer exists to draw.
    cam.standoff = max(v.near_z, cam.standoff)
    cam.float_ = min(1.0, max(0.0, cam.float_))
    cam.float_secs = max(0.5, cam.float_secs)

    d.layers = max(2, int(d.layers))
    d.fog = min(1.0, max(0.0, d.fog))
    d.haze = max(0.0, d.haze)

    bl.amount = max(0.0, bl.amount)
    bl.ceiling = max(1.0, bl.ceiling) if bl.amount > 0 else max(0.0, bl.ceiling)

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
