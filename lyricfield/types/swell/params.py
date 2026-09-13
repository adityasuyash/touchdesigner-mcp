"""Tunables for the swell type.

A second beatsync renderer, and deliberately not a second look at the same idea.
`pulse_grid` moves *brightness*: the field is a fixed scatter of glyphs and the
beat lights parts of it. `swell` moves **weight and density**: how heavy each
glyph is and how much of the field carries one at all. On the downbeat blanks
fill in and glyphs step up the ramp `.:-=+*#`; over the bar they thin back out.

Two things recommend that over another brightness renderer. It needs no channel
the network does not already carry, and because it expresses the beat as
coverage rather than luminance it sidesteps the stacking rule entirely -- the
brightest cell on the loudest beat is no brighter than the dimmest one, so the
glow chain amplifies the shape instead of clipping it.

`Grid`, `Look` and `Analysis` are imported from `lyric_grid` for the same reason
`pulse_grid` imports them: they describe the network, and all three types share
one network.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..lyric_grid.params import RANGES as GRID_RANGES
from ..lyric_grid.params import Analysis, Grid, Look, reconcile_look


@dataclass
class Swell:
    """How much of the field is occupied, and how heavily.

    Coverage is one number per frame. A cell carries a glyph when its fixed
    random bias falls under the current coverage, and the further under it
    falls the heavier the glyph -- so a rise both fills blanks in and thickens
    what is already there, from one value, with nothing moving.
    """
    bar_beats: float = 4.0       # beats in one swell, measured off the beat grid
    attack: float = 0.14         # share of the bar spent opening
    open_min: float = 0.16       # coverage at the trough
    open_max: float = 0.84       # coverage at the crest
    glyphs: str = ".:-=+*#"      # lightest to heaviest; the ramp IS the renderer
    lit_at: float = 0.78         # weight at which a glyph joins the bold layer

    # Track structure. These three facts are measured for every song and no
    # beatsync renderer read any of them before, so the piece had no beginning,
    # no arrival and no ending.
    intro_open: float = 0.30     # coverage multiplier before the drums enter
    arrive: float = 0.78         # ... between the kick entry and the hi-hats
    outro: float = 14.0          # seconds over which it thins away at the end

    kick_open: float = 0.30      # extra weight in a ring, on a kick
    kick_time: float = 0.55
    kick_sigma: float = 2.4
    snare_frac: float = 0.07     # share of cells driven to the top of the ramp
    snare_time: float = 0.28
    high_grain: float = 0.22     # hi-hats roughen the weight field
    reroll: float = 16.0         # seconds between re-scattering the bias


@dataclass
class Params:
    grid: Grid = field(default_factory=Grid)
    look: Look = field(default_factory=Look)
    analysis: Analysis = field(default_factory=Analysis)
    swell: Swell = field(default_factory=Swell)

    def regions(self) -> dict[str, tuple[int, int, int, int]]:
        """The same crops the other two types measure: the band is where
        anything may be drawn and below it must stay black."""
        g = self.grid
        y0 = int(g.band_top * g.height / g.vrows)
        y1 = int((g.band_top + g.band) * g.height / g.vrows)
        out = {"band": (0, y0, g.width, max(1, y1 - y0))}
        below = g.height - y1
        if below >= 2:
            out["lower"] = (0, y1, g.width, below)
        return out

    def validate(self) -> list[str]:
        out: list[str] = []
        g, lk, s = self.grid, self.look, self.swell

        if g.band > g.vrows - g.band_top:
            out.append(
                f"band {g.band} + band_top {g.band_top} exceeds vrows {g.vrows}; "
                "rows would fall outside the frame")
        if g.band < g.vrows - g.band_top - 1:
            dead = (g.vrows - g.band_top - g.band) * (g.height / g.vrows)
            out.append(
                f"band {g.band} leaves {dead:.0f}px of dead space at the bottom "
                f"of frame (vrows {g.vrows})")
        if lk.level_min >= lk.level_max:
            out.append("level_min must be below level_max")
        if lk.level_max > lk.ceil:
            out.append(f"level_max {lk.level_max} exceeds ceil {lk.ceil}")

        # The stacking rule still applies to the *dim* layer's ceiling even
        # though this renderer never adds a lift on top of it.
        stacked = lk.ceil + lk.glow_base * 0.55
        if stacked >= 0.95:
            out.append(
                f"ceil {lk.ceil} plus glow ~{lk.glow_base} will reach "
                f"~{stacked:.2f} at the output")
        if lk.glow_low_knee <= 0:
            out.append("glow_low_knee must be positive; it is a divisor")
        if lk.glow_radius - lk.glow_radius_lfo < 0:
            out.append(
                f"glow_radius {lk.glow_radius} minus its LFO swing "
                f"{lk.glow_radius_lfo} goes negative -- blur size cannot")

        if len(s.glyphs) < 2:
            out.append(
                "glyphs must be a ramp of at least two characters; this "
                "renderer expresses the beat by stepping along it")
        if not (0.0 < s.bar_beats):
            out.append("bar_beats must be positive; it divides the beat period")
        if not (0.0 < s.attack < 1.0):
            out.append(f"attack {s.attack} must be a share of the bar, above 0 "
                       "and below 1")
        if not (0.0 <= s.open_min < s.open_max <= 1.0):
            out.append(
                f"coverage must run {0.0} <= open_min ({s.open_min}) < open_max "
                f"({s.open_max}) <= 1.0")
        if not (0.0 < s.lit_at < 1.0):
            out.append(
                f"lit_at {s.lit_at} must be inside the weight ramp; at 1.0 or "
                "above no glyph ever reaches the bold layer")
        if s.outro <= 0:
            out.append("outro must be positive; it is the length of the ending")
        if not (0.0 < s.intro_open <= 1.0):
            out.append(f"intro_open {s.intro_open} must be above 0 and at most 1")
        if not (0.0 < s.arrive <= 1.0):
            out.append(f"arrive {s.arrive} must be above 0 and at most 1")
        return out


RANGES: dict[str, tuple[float, float, float]] = {
    **{k: v for k, v in GRID_RANGES.items()},
    "bar_beats": (0.5, 16, 0.5), "attack": (0.02, 0.9, 0.01),
    "open_min": (0.0, 0.7, 0.01), "open_max": (0.1, 1.0, 0.01),
    "lit_at": (0.05, 0.99, 0.01),
    "intro_open": (0.02, 1.0, 0.01), "arrive": (0.1, 1.0, 0.01),
    "outro": (0, 60, 1),
    "kick_open": (0, 1, 0.01), "kick_time": (0.05, 2, 0.05),
    "kick_sigma": (0.5, 8, 0.1),
    "snare_frac": (0, 0.4, 0.005), "snare_time": (0.05, 2, 0.05),
    "high_grain": (0, 0.6, 0.01), "reroll": (1, 60, 1),
}
RANGES = {k: v for k, v in RANGES.items()
          if k in {f for s in (Grid(), Look(), Analysis(), Swell())
                   for f in vars(s)}}


@dataclass(frozen=True)
class Control:
    key: str
    label: str
    hint: str
    lead: str
    targets: dict[str, tuple[float, float]]


CONTROLS: tuple[Control, ...] = (
    Control("brightness", "Brightness",
            "How strongly the whole field reads.",
            "look.level_max",
            {"look.level_min": (0.04, 0.16), "look.level_max": (0.22, 0.46),
             "look.ceil": (0.44, 0.60)}),
    Control("colour", "Colour",
            "The hue of the field, around the colour wheel: low is warm "
            "(red/orange), middle is cool (green/blue), high is violet.",
            "look.dim_hue", {"look.dim_hue": (0.0, 1.0)}),
    Control("glow", "Glow",
            "The bloom around the heaviest glyphs.",
            "look.glow_base",
            {"look.glow_base": (0.30, 0.75), "look.glow_radius": (8.0, 34.0),
             "look.bloom_bright": (0.15, 0.55)}),
    Control("swell", "Swell",
            "How quickly the field thickens and thins again. Higher is quicker.",
            "swell.bar_beats", {"swell.bar_beats": (12.0, 1.0)}),
    Control("beat", "Beat response",
            "How visibly the field answers the drums.",
            "swell.kick_open",
            {"swell.kick_open": (0.0, 0.55), "swell.snare_frac": (0.0, 0.2),
             "swell.high_grain": (0.0, 0.45)}),
    Control("density", "Density",
            "How much of the field carries a glyph at the fullest moment.",
            "swell.open_max",
            {"swell.open_min": (0.04, 0.4), "swell.open_max": (0.35, 1.0)}),
)


def _get(params: "Params", path: str) -> float:
    section, name = path.split(".")
    return float(getattr(getattr(params, section), name))


def _set(params: "Params", path: str, value: float) -> None:
    section, name = path.split(".")
    setattr(getattr(params, section), name, value)


def reconcile(params: "Params") -> None:
    """Settle the relationships `validate()` insists on."""
    reconcile_look(params.look)
    s = params.swell
    s.bar_beats = max(0.5, s.bar_beats)
    s.attack = min(0.9, max(0.02, s.attack))
    s.open_min = min(0.95, max(0.0, s.open_min))
    s.open_max = min(1.0, max(s.open_min + 0.05, s.open_max))
    s.lit_at = min(0.99, max(0.05, s.lit_at))
    s.outro = max(0.0, s.outro) or 1.0
    s.intro_open = min(1.0, max(0.02, s.intro_open))
    s.arrive = min(1.0, max(0.1, s.arrive))


def control_values(params: "Params") -> dict[str, float]:
    out = {}
    for c in CONTROLS:
        lo, hi = c.targets[c.lead]
        v = (_get(params, c.lead) - lo) / (hi - lo) if hi != lo else 0.0
        out[c.key] = round(min(1.0, max(0.0, v)), 4)
    return out


def apply_control(params: "Params", key: str, value: float) -> dict:
    control = next((c for c in CONTROLS if c.key == key), None)
    if control is None:
        raise KeyError(f"no such control: {key}")
    v = min(1.0, max(0.0, float(value)))
    for path, (lo, hi) in control.targets.items():
        _set(params, path, round(lo + (hi - lo) * v, 4))
    reconcile(params)
    return {p: _get(params, p) for p in control.targets}


def controls_payload(params: "Params") -> list[dict]:
    now = control_values(params)
    return [{"key": c.key, "label": c.label, "hint": c.hint,
             "value": now[c.key], "drives": sorted(c.targets)}
            for c in CONTROLS]
