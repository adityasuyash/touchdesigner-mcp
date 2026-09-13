"""Tunables for the pulse-grid type.

A beatsync renderer: it draws the same character field as `lyric_grid` and
expresses the same thing -- light, never motion or scale -- but it has no words
to light, so what travels across it is the beat.

`Grid`, `Look` and `Analysis` are imported from `lyric_grid` rather than copied.
They describe the *network* -- resolution, glyph metrics, the glow chain, the
gates on the audio analysis component -- and both types share that network, so
duplicating them would mean two sets of numbers drifting apart. `Pulse` is the
only section that belongs to this type alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..lyric_grid.params import RANGES as GRID_RANGES
from ..lyric_grid.params import Analysis, Grid, Look, reconcile_look


@dataclass
class Pulse:
    """What crosses the field, and how hard.

    The beat grid is measured per song (`beat_period`, `beat_anchor`), so the
    wave is in time with the track rather than free-running.
    """
    wave_beats: float = 4.0      # beats for one pass across the field
    wave_width: float = 3.5      # thickness of the crest, in cells
    wave_lift: float = 0.34      # how much brighter the crest is
    vertical: bool = False       # travel down instead of across
    density: float = 0.72        # share of cells carrying a glyph
    glyphs: str = ".:-=+*#"      # dimmest to brightest
    lit_at: float = 0.52         # brightness at which a cell joins the bold layer
    kick_lift: float = 0.26      # radial ripple on a kick
    kick_time: float = 0.55
    kick_sigma: float = 2.2
    snare_frac: float = 0.06     # share of cells that spark on a snare
    snare_peak: float = 0.5
    snare_time: float = 0.25
    high_lift: float = 0.18      # hi-hat shimmer
    reroll: float = 12.0         # seconds between re-scattering the glyphs


@dataclass
class Params:
    grid: Grid = field(default_factory=Grid)
    look: Look = field(default_factory=Look)
    analysis: Analysis = field(default_factory=Analysis)
    pulse: Pulse = field(default_factory=Pulse)

    def regions(self) -> dict[str, tuple[int, int, int, int]]:
        """The same crops `lyric_grid` measures, for the same reason: the band
        is where anything may be drawn and below it must stay black."""
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
        g, lk, p = self.grid, self.look, self.pulse

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

        # The same stacking rule as the lyric type, and for the same measured
        # reason: brightness adds at the output, and nothing that is not the
        # beat's own crest may reach 1.0.
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

        if p.wave_beats <= 0:
            out.append("wave_beats must be positive; it divides the beat period")
        if p.wave_width <= 0:
            out.append("wave_width must be positive")
        if not p.glyphs:
            out.append("glyphs cannot be empty; there would be nothing to draw")
        if not (0.0 < p.density <= 1.0):
            out.append(f"density {p.density} must be above 0 and at most 1")
        if p.lit_at > lk.ceil + p.wave_lift:
            out.append(
                f"lit_at {p.lit_at} is above anything the field can reach "
                f"({lk.ceil + p.wave_lift:.2f}), so nothing would ever light")
        return out


RANGES: dict[str, tuple[float, float, float]] = {
    # the shared sections keep the bounds they already have
    **{k: v for k, v in GRID_RANGES.items()},
    # pulse
    "wave_beats": (0.5, 16, 0.5), "wave_width": (0.5, 12, 0.1),
    "wave_lift": (0, 1, 0.01), "density": (0.1, 1.0, 0.01),
    "lit_at": (0, 1, 0.01),
    "kick_lift": (0, 1, 0.01), "kick_time": (0.05, 2, 0.05),
    "kick_sigma": (0.5, 8, 0.1),
    "snare_frac": (0, 0.4, 0.005), "snare_peak": (0, 1, 0.01),
    "snare_time": (0.05, 2, 0.05),
    "high_lift": (0, 1, 0.01), "reroll": (1, 60, 1),
}
# Bounds for tunables the shared sections no longer carry here.
RANGES = {k: v for k, v in RANGES.items()
          if k in {f for s in (Grid(), Look(), Analysis(), Pulse())
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
            "The bloom around the brightest cells.",
            "look.glow_base",
            {"look.glow_base": (0.30, 0.75), "look.glow_radius": (8.0, 34.0),
             "look.bloom_bright": (0.15, 0.55)}),
    Control("sweep", "Sweep",
            "How fast the pulse crosses the field. Higher is quicker.",
            "pulse.wave_beats", {"pulse.wave_beats": (12.0, 1.0)}),
    Control("beat", "Beat response",
            "How visibly the field answers the drums.",
            "pulse.kick_lift",
            {"pulse.kick_lift": (0.0, 0.45), "pulse.snare_peak": (0.15, 0.6),
             "pulse.high_lift": (0.0, 0.35)}),
    Control("density", "Density",
            "How much of the field carries a glyph at all.",
            "pulse.density", {"pulse.density": (0.25, 1.0)}),
)


def _get(params: "Params", path: str) -> float:
    section, name = path.split(".")
    return float(getattr(getattr(params, section), name))


def _set(params: "Params", path: str, value: float) -> None:
    section, name = path.split(".")
    setattr(getattr(params, section), name, value)


def reconcile(params: "Params") -> None:
    """Settle the relationships `validate()` insists on."""
    reconcile_look(params.look)      # the shared look rules, unchanged
    lk, p = params.look, params.pulse
    p.lit_at = min(p.lit_at, lk.ceil + p.wave_lift)
    p.wave_beats = max(0.5, p.wave_beats)
    p.wave_width = max(0.5, p.wave_width)
    p.density = min(1.0, max(0.05, p.density))


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
