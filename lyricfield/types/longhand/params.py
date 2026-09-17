"""Longhand's tunables: lyrics lettered by hand over footage.

From the Chainsmokers' "Closer" lyric video, built this time from frames of it
rather than from descriptions of it. What the frames show: thick white marker
lettering sitting FLAT and LARGE over live action, a lyric phrase at a time,
mixed caps and lowercase inside a single word, letters of different sizes, a
baseline that wanders.

Three earlier readings were wrong in three different directions -- words flying
at the camera, a pan along one long written line, words scattered through a
volume -- and all three lean on the same published sentence about lyrics that
"fly through 3d space". That describes the one aerial shot, where the lettering
is tracked onto a landscape. The type never moves through space at all.

So the vocabulary is a sheet and a hand: how a phrase is broken and set, how
irregular the lettering is, and what it sits on.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .._controls import Control, bind_controls


@dataclass
class Stage:
    """The frame, and the hand the words are written in."""

    width: int = 720
    height: int = 1280
    # Marker Felt is the dry marker the reference uses. Bradley Hand -- what
    # this renderer used while it was a different idea -- is thin and cursive;
    # Chalkduster is too textured, SignPainter too clean.
    # Bradley Hand. Chosen from four still frames, this was Marker Felt; the
    # moving frames say otherwise -- the reference's lettering is a cursive
    # brush with connected, looping strokes ("Bite that tattoo on your
    # shoulder"), not an upright marker with separated letters.
    font: str = "Bradley Hand"
    # Letter height in pixels, before the per-letter variation. Big: the
    # reference fills most of the frame width with three or four words.
    size: float = 112.0
    # Where the block sits, 0..1. Slightly above centre, as the reference is
    # more often than not.
    center_x: float = 0.5
    center_y: float = 0.47


@dataclass
class Line:
    """How a phrase is broken up and stacked."""

    # A phrase may not exceed any of these. The renderer splits each
    # transcription line into near-equal parts until all three hold -- measured
    # on a real song, its 121 cues fall into 12 lines of 3 to 32 words, the
    # first spanning 11.4 seconds, which is nothing like the reference.
    max_words: int = 5
    max_chars: int = 26
    max_seconds: float = 3.5
    # How wide a drawn row may get before it wraps, as a share of the frame.
    wrap: float = 0.86
    # Space between rows, as a multiple of the letter height. Generous: the
    # reference leaves about a line of air between them.
    leading: float = 1.30
    # Seconds a phrase stays up after its last word, when nothing follows. One
    # gap in the benchmark song is 15.4 seconds, and holding a phrase through
    # that is a frozen frame rather than a lyric video.
    linger: float = 2.6
    # How far each row is pushed right of the one above, as a share of the
    # frame. The reference stacks them ragged, not centred: "that I KNOW" /
    # "you CAN't" / "AFFOrD" each start about this much right of the last.
    indent: float = 0.04


@dataclass
class Hand:
    """How irregular the lettering is. This is the whole signature.

    Every value here is applied per LETTER, from a pure function of its index,
    so the same song letters the same way on any machine and a re-render is
    identical.
    """

    # How many sizes the letters are drawn at, and how far apart. Three Text
    # TOPs at 1-spread, 1, 1+spread; one step is uniform lettering.
    steps: int = 3
    spread: float = 0.11
    # Baseline wander and tracking wobble, as a share of the letter height.
    waver: float = 0.055
    jitter: float = 0.05
    # How often a letter comes out capitalised, 0..1. The reference's "CAN'4
    # Stop" and "you CAN't AFFORD" are the most recognisable thing about it.
    shout: float = 0.34
    # Degrees the block is rotated. A hand does not rule a line.
    tilt: float = 1.6
    # How hard one word per phrase is picked out. Two of the references set one
    # word large and the rest of the phrase small -- at 1 the chosen word is
    # drawn entirely from the largest step and everything else from the
    # smallest, at 0 the sizes are the hand's own scatter and nothing is
    # picked out. Needs `steps` above 1; there is nothing to pick from
    # otherwise.
    emphasis: float = 0.0


@dataclass
class Drift:
    """The camera. The lettering itself never moves.

    "In closer music video, the words fly in and out of the screen, as if all
    the words were filmed by an actual camera that was handheld and physically
    being moved from word to word." That is the model: each phrase is written
    somewhere on a sheet and a hand-held camera swings between them.

    Two earlier readings of this were wrong -- first a cut, then a smooth
    constant-velocity slide -- and the second was wrong in KIND rather than in
    amount. Measured off the video at 25fps (the first measurement sampled at
    8fps, which is slower than the motion itself), over 353 frame-to-frame
    steps of the lettering's centroid:

        holding      median 2.09 px/frame on a 320-wide sample = 0.65% of width
        transits     median 6.33 px/frame, peak 20.1 px = 6.3% of width
        direction reverses between frames: 55% in x, 40% in y

    A drift never reverses. A hand reverses constantly.
    """

    # The slow float, and the tremor on top of it, as shares of the frame
    # width. `field.py` picks the frequency bands; these set how far they
    # reach. At the shipped values the measured per-frame step is 0.66% of the
    # width with reversals at 51%/49%, against the 0.65% and 55%/40% above.
    sway: float = 0.035
    tremor: float = 0.012
    # Seconds the camera takes to swing onto the next phrase. It overshoots
    # slightly and settles, and the outgoing phrase is carried off the edge by
    # the same move -- which is what "fly in and out" means.
    whip: float = 0.30
    # How far a phrase's place on the sheet strays from the middle, as a share
    # of the frame. This is also how far the camera has to travel at a
    # hand-over, so it sets how violent the transits are. Without it every
    # phrase would be written in the same spot, the camera would never move,
    # and a hand-over would stack the outgoing phrase behind the incoming one.
    place: float = 0.15
    # Seconds the outgoing phrase stays up after the next one lands. They
    # overlap, both part-faded, which is what makes it a hand-over rather than
    # a cut -- measured at about a quarter of a second.
    fade: float = 0.28
    # How faint the outgoing phrase gets while it leaves.
    ghost: float = 0.45


@dataclass
class Ground:
    """What the lettering sits on.

    The song's own footage when it has any (`Track.plate`), and a generated
    stand-in when it does not -- which is what a style preview records against,
    since a preview deliberately carries nothing of the loaded song.
    """

    # How far the plate is brought down before the lettering goes over it.
    # White marker over a bright sky needs the sky darkened; the reference does
    # that rather than outlining the type, which would stop it looking drawn.
    dim: float = 0.42
    # The generated stand-in: how warm, how bright, how fast it drifts.
    hue: float = 0.07
    sat: float = 0.42
    lift: float = 0.52
    drift_secs: float = 14.0
    # Softness of the stand-in, in pixels. Large: it stands in for something
    # shot at a wide aperture.
    blur: float = 90.0


@dataclass
class Look:
    # The lettering. White, near enough -- the reference's is not tinted.
    ink: float = 0.97
    # ... but the other three references this renderer now carries are: blue
    # marker on light paper, and a bold sans in one accent colour. `ink_hue`
    # and `ink_sat` rather than `hue` and `sat`: `Ground` already has those
    # two, and `Config` flattens every section into one namespace, so two
    # sections sharing a name keep whichever came last.
    ink_hue: float = 0.0
    ink_sat: float = 0.0
    glow: float = 0.18
    bloom: float = 10.0


@dataclass
class Beat:
    """What the drums do inside this renderer, as opposed to the response
    chain that sits after every renderer."""

    kick_lift: float = 0.05
    kick_time: float = 0.22
    intro_open: float = 0.35
    arrive: float = 0.88
    outro: float = 10.0


def ink_luma(look: "Look") -> float:
    """How bright the lettering actually comes out, 0..1.

    Its colour matters, not just its level: a saturated blue at full value
    reads at about a fifth of white. Rec.709 weights, which is what the eye
    does and what every brightness check in this project measures.
    """
    from .build import _rgb

    r, g, b = _rgb(look.ink_hue, look.ink_sat)
    return look.ink * (0.2126 * r + 0.7152 * g + 0.0722 * b)


def ground_level(ground: "Ground", beat: "Beat") -> float:
    """How bright the plate sits once a kick has lifted it."""
    return (1.0 - ground.dim) + beat.kick_lift


@dataclass
class Params:
    stage: Stage = field(default_factory=Stage)
    line: Line = field(default_factory=Line)
    hand: Hand = field(default_factory=Hand)
    drift: Drift = field(default_factory=Drift)
    ground: Ground = field(default_factory=Ground)
    look: Look = field(default_factory=Look)
    beat: Beat = field(default_factory=Beat)

    def validate(self) -> list[str]:
        out: list[str] = []
        s, ln, h, g, lk, b = (self.stage, self.line, self.hand, self.ground,
                              self.look, self.beat)
        dr = self.drift

        if s.size <= 0:
            out.append("size must be positive; it is a letter height")
        for name, v in (("center_x", s.center_x), ("center_y", s.center_y)):
            if not (0.0 <= v <= 1.0):
                out.append(f"{name} {v} is outside the frame")

        if ln.max_words < 1:
            out.append("max_words must be at least 1, or a phrase has no words")
        if ln.max_chars < 4:
            out.append(
                f"max_chars {ln.max_chars} is shorter than most single words, "
                "so every phrase would be one word and the breaks arbitrary")
        if ln.max_seconds <= 0:
            out.append("max_seconds must be positive; it is a duration")
        if not (0.2 <= ln.wrap <= 1.0):
            out.append(f"wrap {ln.wrap} is a share of the frame width")
        if ln.leading <= 0:
            out.append("leading must be positive, or the rows sit on each other")
        if ln.linger <= 0:
            out.append("linger must be positive; it is how long a phrase stays")

        if h.steps < 1:
            out.append("steps must be at least 1; 1 is uniform lettering")
        if h.spread < 0:
            out.append("spread is a size difference and cannot be negative")
        if h.steps > 1 and h.spread <= 0:
            out.append(
                f"steps {h.steps} with no spread draws one size {h.steps} times "
                "over -- the operators cost something and buy nothing")
        for name, v in (("waver", h.waver), ("jitter", h.jitter)):
            if v < 0:
                out.append(f"{name} is a displacement and cannot be negative")
        if not (0.0 <= h.shout <= 1.0):
            out.append(f"shout {h.shout} is a share of letters, 0 to 1")
        if not (0.0 <= h.emphasis <= 1.0):
            out.append(f"emphasis {h.emphasis} is a share, 0 to 1")
        if h.emphasis > 0 and h.steps < 2:
            out.append(
                f"emphasis {h.emphasis} with steps {h.steps} has no larger "
                "size to draw the picked word at")
        for name, v in (("ink_hue", lk.ink_hue), ("ink_sat", lk.ink_sat)):
            if not (0.0 <= v <= 1.0):
                out.append(f"{name} {v} is a share, 0 to 1")

        for name, v in (("sway", dr.sway), ("tremor", dr.tremor)):
            if v < 0:
                out.append(f"{name} is a distance and cannot be negative")
        if dr.whip <= 0:
            out.append(
                "whip must be positive; a camera that arrives instantly is a "
                "cut, which is the thing this renderer was missing")
        if dr.whip > ln.max_seconds:
            out.append(
                f"whip {dr.whip} is longer than max_seconds {ln.max_seconds}, "
                "so the camera would never finish arriving before the next "
                "phrase pulls it away")
        if dr.fade < 0:
            out.append("fade is a duration and cannot be negative")
        if dr.fade >= ln.linger:
            out.append(
                f"fade {dr.fade} is as long as linger {ln.linger}, so a phrase "
                "would still be handing over when it is already gone")
        if dr.place < 0:
            out.append("place is a distance and cannot be negative")
        if not (0.0 <= dr.ghost <= 1.0):
            out.append(f"ghost {dr.ghost} is a brightness share, 0 to 1")

        if not (0.0 <= g.dim <= 1.0):
            out.append(f"dim {g.dim} is a share of the plate's brightness")
        if g.drift_secs <= 0:
            out.append("drift_secs must be positive; it is a period")
        if g.blur < 0:
            out.append("blur is a radius and cannot be negative")

        # The lettering IS the cued word, so it is allowed to reach white --
        # that is the one thing this project's brightness rule permits. What
        # has to hold is CONTRAST, and in EITHER direction. A first version of
        # this check asked that ink plus glow stay under white, which is the
        # wrong question and refused a legitimate near-white marker. A second
        # asked that the ground sit below the ink, which is the right question
        # asked one way round: this renderer now also has to carry dark ink on
        # light paper, where the ground is meant to be the brighter of the two.
        lum, ground = ink_luma(lk), ground_level(g, b)
        if ground > 1.0:
            out.append(
                f"the plate reaches {ground:.2f} once a kick lifts it, which "
                "is past white -- it clips flat, and lettering of any colour "
                "goes with it")
        if abs(lum - ground) < 0.25:
            out.append(
                f"the lettering reads at {lum:.2f} and the plate at "
                f"{ground:.2f} once a kick lifts it -- {abs(lum - ground):.2f} "
                "apart is not enough for one to read against the other")
        if b.outro <= 0:
            out.append("outro must be positive; it is the length of the ending")
        if not (0.0 < b.intro_open <= 1.0):
            out.append(f"intro_open {b.intro_open} must be above 0 and at most 1")
        if not (0.0 < b.arrive <= 1.0):
            out.append(f"arrive {b.arrive} must be above 0 and at most 1")
        return out

    def regions(self) -> dict[str, tuple[int, int, int, int]]:
        """Where the lettering lands. Not `band`/`lower`, which mean "inside
        the character grid" and there is no grid here."""
        s, ln = self.stage, self.line
        h = int(s.size * ln.leading * 3.2)
        y = int(max(0, min(s.height - h, s.height * (1.0 - s.center_y) - h / 2)))
        return {"lettering": (0, y, s.width, h)}


def hand_sizes(params: "Params") -> list[float]:
    """The letter height each Text TOP is fixed at, smallest first.

    A Text TOP has ONE font size for its whole Specification DAT, so per-letter
    variation is not available inside one of them: the range is cut into steps,
    each its own TOP, and a letter is drawn by whichever step it was assigned.
    `field.py` assigns from this same list, so the size a letter is drawn at
    cannot drift from the size its layout was measured at.
    """
    s, h = params.stage, params.hand
    n = max(1, int(h.steps))
    if n == 1:
        return [s.size]
    lo = s.size * (1.0 - h.spread)
    step = (s.size * (1.0 + h.spread) - lo) / (n - 1)
    return [round(lo + step * i, 3) for i in range(n)]


RANGES: dict[str, tuple] = {
    "width": (240, 2160, 2), "height": (240, 3840, 2),
    "size": (30.0, 260.0, 1.0),
    "center_x": (0.0, 1.0, 0.01), "center_y": (0.0, 1.0, 0.01),
    "max_words": (1, 12, 1), "max_chars": (6, 60, 1),
    "max_seconds": (0.5, 12.0, 0.1), "wrap": (0.2, 1.0, 0.01),
    "leading": (0.8, 2.5, 0.05), "linger": (0.2, 10.0, 0.1),
    "indent": (0.0, 0.2, 0.005),
    "sway": (0.0, 0.2, 0.005), "tremor": (0.0, 0.08, 0.001),
    "whip": (0.05, 1.2, 0.01),
    "fade": (0.0, 2.0, 0.02), "ghost": (0.0, 1.0, 0.01),
    "place": (0.0, 0.4, 0.01),
    "steps": (1, 5, 1), "spread": (0.0, 0.4, 0.01),
    "waver": (0.0, 0.3, 0.005), "jitter": (0.0, 0.3, 0.005),
    "shout": (0.0, 1.0, 0.01), "tilt": (0.0, 12.0, 0.1),
    "emphasis": (0.0, 1.0, 0.01),
    "dim": (0.0, 1.0, 0.01),
    "hue": (0, 1, 0.01), "sat": (0, 1, 0.01), "lift": (0.0, 1.0, 0.01),
    "drift_secs": (2.0, 60.0, 0.5), "blur": (0.0, 300.0, 1.0),
    "ink": (0.2, 1.0, 0.01), "glow": (0, 1, 0.01), "bloom": (0, 60, 1),
    "ink_hue": (0.0, 1.0, 0.01), "ink_sat": (0.0, 1.0, 0.01),
    "kick_lift": (0.0, 0.4, 0.01), "kick_time": (0.05, 2.0, 0.05),
    "intro_open": (0.02, 1.0, 0.01), "arrive": (0.1, 1.0, 0.01),
    "outro": (0, 60, 1),
}


CONTROLS: tuple[Control, ...] = (
    Control("hand", "Hand",
            "How large the lettering is.",
            "stage.size", {"stage.size": (64.0, 150.0)}),
    Control("rough", "Rough",
            "How far from a font the lettering strays.",
            "hand.waver", {"hand.waver": (0.0, 0.13),
                           "hand.jitter": (0.0, 0.12),
                           "hand.spread": (0.0, 0.22),
                           "hand.tilt": (0.0, 4.0)}),
    Control("emphasis", "Emphasis",
            "How hard one word of each phrase is picked out, large.",
            "hand.emphasis", {"hand.emphasis": (0.0, 1.0)}),
    Control("shout", "Shout",
            "How many letters come out in capitals.",
            "hand.shout", {"hand.shout": (0.0, 0.75)}),
    Control("phrase", "Phrase",
            "How much of the lyric is on screen at once.",
            "line.max_words", {"line.max_words": (2, 9),
                               "line.max_chars": (14, 44),
                               "line.max_seconds": (1.6, 6.0)}),
    Control("camera", "Camera",
            "How far the camera swings between phrases, and how hard it "
            "shakes while it holds.",
            "drift.place", {"drift.place": (0.0, 0.30),
                            "drift.sway": (0.0, 0.08),
                            "drift.tremor": (0.0, 0.03)}),
    Control("ground", "Ground",
            "How far the footage is brought down behind the words.",
            "ground.dim", {"ground.dim": (0.0, 0.75)}),
)


def reconcile(params: "Params") -> None:
    """Settle the relationships `validate()` insists on."""
    s, ln, h, g, lk, b = (params.stage, params.line, params.hand, params.ground,
                          params.look, params.beat)

    s.size = max(1.0, s.size)
    s.center_x = min(1.0, max(0.0, s.center_x))
    s.center_y = min(1.0, max(0.0, s.center_y))

    ln.max_words = max(1, int(ln.max_words))
    ln.max_chars = max(4, int(ln.max_chars))
    ln.max_seconds = max(0.1, ln.max_seconds)
    ln.wrap = min(1.0, max(0.2, ln.wrap))
    ln.leading = max(0.1, ln.leading)
    ln.linger = max(0.1, ln.linger)
    ln.indent = max(0.0, ln.indent)
    dr = params.drift
    dr.sway = max(0.0, dr.sway)
    dr.tremor = max(0.0, dr.tremor)
    dr.whip = min(max(0.01, dr.whip), ln.max_seconds)
    dr.ghost = min(1.0, max(0.0, dr.ghost))
    dr.place = max(0.0, dr.place)
    dr.fade = min(max(0.0, dr.fade), ln.linger * 0.9)

    h.steps = max(1, int(h.steps))
    h.spread = max(0.0, h.spread)
    if h.steps > 1 and h.spread <= 0:
        h.steps = 1
    h.waver = max(0.0, h.waver)
    h.jitter = max(0.0, h.jitter)
    h.shout = min(1.0, max(0.0, h.shout))
    h.tilt = max(0.0, h.tilt)
    h.emphasis = min(1.0, max(0.0, h.emphasis))
    if h.steps < 2:
        h.emphasis = 0.0

    g.dim = min(1.0, max(0.0, g.dim))
    g.drift_secs = max(0.5, g.drift_secs)
    g.blur = max(0.0, g.blur)

    # In order of what may give way: the kick's lift, then the plate. The
    # lettering's own brightness is legibility and stays.
    lk.ink = min(1.0, max(0.2, lk.ink))
    lk.ink_hue = min(1.0, max(0.0, lk.ink_hue))
    lk.ink_sat = min(1.0, max(0.0, lk.ink_sat))

    # The ground moves away from the ink, in whichever direction it has room
    # to go: down for light lettering, up for dark. In order of what may give
    # way -- the kick's lift, then the plate. The lettering's own brightness is
    # legibility and stays.
    lum = ink_luma(lk)
    # Never past white first, whatever colour the ink is: a plate that clips
    # flat takes the lettering with it, and the contrast the numbers promise
    # is not the contrast the frame shows.
    over = ground_level(g, b) - 1.0
    if over > 0:
        give = min(over, b.kick_lift)
        b.kick_lift, over = b.kick_lift - give, over - give
        if over > 0:
            g.dim = min(1.0, g.dim + over)
    if lum >= 0.5:
        over = ground_level(g, b) - (lum - 0.25)
        if over > 0:
            give = min(over, b.kick_lift)
            b.kick_lift, over = b.kick_lift - give, over - give
        if over > 0:
            g.dim = min(1.0, g.dim + over)
    else:
        under = (lum + 0.25) - ground_level(g, b)
        if under > 0:
            g.dim = max(0.0, g.dim - under)
    b.intro_open = min(1.0, max(0.02, b.intro_open))
    b.arrive = min(1.0, max(0.1, b.arrive))
    b.outro = max(0.0, b.outro) or 1.0


control_values, apply_control, controls_payload = bind_controls(
    CONTROLS, reconcile)
