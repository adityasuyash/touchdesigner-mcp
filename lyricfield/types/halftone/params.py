"""Halftone's tunables: the beat as a dot screen.

Print reproduction as an aesthetic. Tone is carried by the *size* of dots on a
regular lattice, not by their brightness, and each colour separation is screened
at its own angle -- which is where the rosette comes from, and why a halftone
reads as a halftone rather than as a grid of dots.

Nothing here is shared with any other renderer. There is no `cols`, no `vrows`,
no glyph ramp: the lattice is continuous, described by a pitch and an angle, and
the Script TOP writes pixels.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .._controls import Control, bind_controls


# The most the tone terms may sum to. Past this every dot simply sits at its
# maximum and the beat stops being visible at all. Named once because
# `validate` and `reconcile` have to agree about it -- two copies of a number
# like this drift, and the one that drifts is the one nobody reads.
TONE_CAP = 1.25


@dataclass
class Frame:
    """The canvas, and how much of it is actually computed.

    `scale` matters more here than elsewhere: three separations mean three
    rotations and three lattice evaluations per frame, so the field is computed
    small and scaled up. Dots are soft-edged, so nobody can tell.
    """

    width: int = 720
    height: int = 1280
    scale: float = 0.5


@dataclass
class Screen:
    """The lattice the dots sit on."""

    # Dots across the frame's width. The whole difference between a newspaper
    # and a poster.
    pitch: float = 36.0
    # Screen angle in degrees. 45 is the classic single-screen angle, because a
    # lattice on the diagonal is the least visible to the eye.
    angle: float = 45.0
    # Biggest a dot may get, as a fraction of the distance to its neighbour. Above
    # about 0.7 neighbouring dots merge and the screen fills in solid.
    dot: float = 0.62
    # Edge softness, in cell units. Zero would alias badly at this resolution.
    soft: float = 0.13


@dataclass
class Tone:
    """What the dots are a picture *of*: one field, built from the drums."""

    base: float = 0.10
    kick_lift: float = 0.55
    kick_time: float = 0.30
    snare_lift: float = 0.30
    snare_time: float = 0.22
    hat_lift: float = 0.12
    hat_time: float = 0.14
    # A slow swell travelling across the frame, so a quiet stretch is not static.
    wave: float = 0.18
    wave_beats: float = 8.0
    # How much darker the corners are than the middle. A flat tone field screens
    # to a flat sheet of identical dots, which reads as wallpaper.
    vignette: float = 0.55


@dataclass
class Ink:
    hue: float = 0.08
    sat: float = 0.35
    # Three screens instead of one, each at its own angle, one per channel. This
    # is the identifiable version: the offset angles beat against each other and
    # make the rosette.
    separate: bool = True
    # Degrees between one separation's screen and the next. 30 is the printer's
    # answer; small values moire badly, which is the thing angles exist to avoid.
    spread: float = 30.0


@dataclass
class Look:
    glow: float = 0.26
    bloom: float = 10.0


@dataclass
class Beat:
    intro_open: float = 0.30
    arrive: float = 0.82
    outro: float = 10.0


@dataclass
class Params:
    frame: Frame = field(default_factory=Frame)
    screen: Screen = field(default_factory=Screen)
    tone: Tone = field(default_factory=Tone)
    ink: Ink = field(default_factory=Ink)
    look: Look = field(default_factory=Look)
    beat: Beat = field(default_factory=Beat)

    def validate(self) -> list[str]:
        out: list[str] = []
        f, s, t, i, b = (self.frame, self.screen, self.tone, self.ink, self.beat)
        if not (0.1 <= f.scale <= 1.0):
            out.append(f"scale {f.scale} must be between 0.1 and 1")
        if s.pitch < 2:
            out.append("pitch must be at least 2; it is dots across the frame")
        if s.dot <= 0:
            out.append("dot must be positive, or nothing is ever drawn")
        if s.dot > 0.75:
            out.append(
                f"dot {s.dot} merges neighbouring dots into a solid sheet; the "
                "screen stops reading as a screen above about 0.7")
        if s.soft <= 0:
            out.append(
                "soft must be positive; a hard dot edge aliases into a mess at "
                "this resolution")
        if i.separate and i.spread <= 0:
            out.append(
                "spread must be positive when the inks are separated, or all "
                "three screens land on the same angle and there is no rosette")
        # Tone is what drives dot AREA, so it is the thing that must stay inside
        # 0..1 -- past 1 every dot is simply at its maximum and the beat stops
        # being visible at all.
        stacked = t.base + t.kick_lift + t.snare_lift + t.hat_lift + t.wave
        if stacked > TONE_CAP:
            out.append(
                f"base {t.base} plus a kick at {t.kick_lift}, a snare at "
                f"{t.snare_lift}, hats at {t.hat_lift} and a wave at {t.wave} "
                f"reach ~{stacked:.2f}; the screen saturates")
        if not (0.0 <= t.vignette < 1.0):
            out.append(f"vignette {t.vignette} must be at least 0 and below 1")
        if t.wave_beats <= 0:
            out.append("wave_beats must be positive; it is a period")
        for name, v in (("kick_time", t.kick_time), ("snare_time", t.snare_time),
                        ("hat_time", t.hat_time)):
            if v <= 0:
                out.append(f"{name} must be positive; it is a decay")
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
    "pitch": (4, 160, 1), "angle": (0, 90, 1),
    "dot": (0.05, 0.75, 0.01), "soft": (0.01, 0.5, 0.01),
    "base": (0.0, 0.6, 0.01),
    "kick_lift": (0.0, 1.0, 0.01), "kick_time": (0.05, 2.0, 0.01),
    "snare_lift": (0.0, 1.0, 0.01), "snare_time": (0.05, 2.0, 0.01),
    "hat_lift": (0.0, 0.6, 0.01), "hat_time": (0.02, 1.0, 0.01),
    "wave": (0.0, 0.6, 0.01), "wave_beats": (0.5, 32.0, 0.5),
    "vignette": (0.0, 0.95, 0.01),
    "hue": (0, 1, 0.01), "sat": (0, 1, 0.01),
    "separate": (0, 1, 1), "spread": (1.0, 60.0, 1.0),
    "glow": (0, 1, 0.01), "bloom": (0, 60, 1),
    "intro_open": (0.02, 1.0, 0.01), "arrive": (0.1, 1.0, 0.01),
    "outro": (0, 60, 1),
}


CONTROLS: tuple[Control, ...] = (
    Control("screen", "Screen",
            "How fine the dot grid is, from a poster to a newspaper.",
            "screen.pitch", {"screen.pitch": (12.0, 110.0),
                             "screen.soft": (0.2, 0.07)}),
    Control("weight", "Weight",
            "How large the dots grow, from a pale wash to nearly solid ink.",
            "screen.dot", {"screen.dot": (0.3, 0.72),
                           "tone.base": (0.03, 0.22)}),
    Control("drive", "Drive",
            "How hard the drums swell the dots.",
            "tone.kick_lift", {"tone.kick_lift": (0.15, 0.9),
                               "tone.snare_lift": (0.1, 0.5)}),
    Control("glow", "Glow",
            "The halo around the ink, and how far it spreads.",
            "look.glow", {"look.glow": (0.04, 0.6),
                          "look.bloom": (3.0, 30.0)}),
)


def reconcile(params: "Params") -> None:
    """Settle the relationships `validate()` insists on."""
    f, s, t, i, b = (params.frame, params.screen, params.tone, params.ink,
                     params.beat)
    f.scale = min(1.0, max(0.1, f.scale))
    s.pitch = max(2.0, s.pitch)
    s.dot = min(0.75, max(0.01, s.dot))
    s.soft = max(0.01, s.soft)
    if i.separate:
        i.spread = max(1.0, i.spread)
    t.vignette = min(0.95, max(0.0, t.vignette))
    t.wave_beats = max(0.5, t.wave_beats)
    t.kick_time = max(0.01, t.kick_time)
    t.snare_time = max(0.01, t.snare_time)
    t.hat_time = max(0.01, t.hat_time)
    # In order of what may give way: the wave first, then the hats, then the
    # snare, then the paper's own grey. The kick is the one the picture is
    # keyed to and it keeps what it was asked for. `base` has to be in this
    # list -- leaving it out let a heavy base and a heavy kick alone exceed the
    # cap with nothing left to surrender, so `reconcile` returned a config its
    # own `validate` rejected.
    # A hair under the cap, not exactly on it: subtracting floats lands a few
    # parts in 10^16 above the target often enough that `reconcile` returned a
    # config its own `validate` then rejected.
    over = ((t.base + t.kick_lift + t.snare_lift + t.hat_lift + t.wave)
            - (TONE_CAP - 1e-6))
    for name in ("wave", "hat_lift", "snare_lift", "base"):
        if over <= 0:
            break
        give = min(over, getattr(t, name))
        setattr(t, name, getattr(t, name) - give)
        over -= give
    b.intro_open = min(1.0, max(0.02, b.intro_open))
    b.arrive = min(1.0, max(0.1, b.arrive))
    b.outro = max(0.0, b.outro) or 1.0


control_values, apply_control, controls_payload = bind_controls(
    CONTROLS, reconcile)
