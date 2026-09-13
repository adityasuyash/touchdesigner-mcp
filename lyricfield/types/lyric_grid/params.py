"""Tunables for the lyric-grid type, and the constraints between them.

These values were arrived at by measurement during the TouchDesigner build, not
by taste, and several interact in ways that are easy to get wrong:

  * `spark_peak` and `ripple_lift` stack on top of `glow_base` before reaching
    the output. Set naively (0.75 / 0.40) they measured 0.99 at /project1/out --
    indistinguishable from a cued word. Change them together and re-measure.
  * Nothing except a cued word may reach 1.0. `ceil` is the hard cap applied in
    the field script before the glow is composited.
  * `band` rows must fit inside `vrows`. Leaving band < vrows-1 puts dead black
    at the bottom of frame; that bug shipped in three versions.

`validate()` encodes those constraints so a bad combination is refused before a
two-minute render discovers it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Grid:
    cols: int = 24
    vrows: int = 24
    band: int = 22
    band_top: int = 1
    # Share of the band's cells one stanza of lyrics may ask for. Letters sit on
    # every other cell along a continuous path, so the hard ceiling is about
    # half; contiguity costs more again, so the usable share is lower still.
    # Stanzas are grouped to fit this rather than to a fixed line count -- five
    # long lines wanted 488 of 528 cells, and the lines that would not place
    # were dropped, so their words were sung with nothing on screen to light.
    letter_frac: float = 0.28
    font: str = "Courier New"
    font_px: float = 50.0
    # Vertical em as a fraction of font_px. The hand-built network never set
    # fontsizey at all, leaving TouchDesigner's 30-POINT default (40px at 96dpi)
    # against a 50-pixel fontsizex -- so the row pitch silently depended on the
    # display's DPI. 0.8 is that 40/50 ratio, now stated rather than inherited.
    glyph_aspect: float = 0.8
    width: int = 720
    height: int = 1280


@dataclass
class Look:
    dim_hue: float = 0.58
    dim_sat: float = 0.35
    level_min: float = 0.10
    level_max: float = 0.38
    ceil: float = 0.58          # hard cap for anything not cued
    drift_min: float = 3.0
    drift_max: float = 6.0
    dissolve: float = 2.5
    # The glow chain. These are read by build.py, not field.py: they are the
    # literals that used to be baked into the v9_glow_* expressions, where they
    # drifted out of step with this file (config said radius 20, the network
    # evaluated 23) because nothing generated the expression from them.
    glow_base: float = 0.62         # v9_glow_lvl brightness, constant term
    glow_lfo: float = 0.08          # ... its LFO term
    glow_low: float = 0.10          # ... its low-band term
    glow_low_knee: float = 0.32     # low-band value that saturates that term
    glow_radius: float = 20.0       # v9_glow_blur size, constant term
    glow_radius_lfo: float = 5.0    # ... its LFO term
    glow_lfo_hz: float = 0.06       # v9_lfo frequency
    bloom_size: float = 9.0         # v7_bloom, the tight bloom on lit words
    bloom_bright: float = 0.35      # v7_bloom_lvl


@dataclass
class Cueing:
    ramp_up: float = 0.12
    hold: float = 1.05          # how long a word sits at full brightness
    ramp_dn: float = 0.32
    lead: float = 0.15
    # Per-letter jitter on when a letter lights, in seconds. Without it every
    # letter of a word lights on the same frame, which reads as a word being
    # switched on rather than sung. This cannot reuse the existing per-letter
    # `stag`, which staggers only the dim layer's crossfade and deliberately
    # does not touch lighting.
    letter_spread: float = 0.06
    offset: float = 0.0         # global nudge, applied to every cue
    stanza_size: int = 5
    ambient_target: int = 190
    # Also the smallest lyric gap worth its own layout: a hole shorter than this
    # stays with the stanza before it rather than recomposing the whole field
    # for three seconds. See field.py::_stanzas.
    ambient_cycle: float = 6.0
    # Blank cells between one word and the next along a line's path. The range
    # is the randomness: 2..4 laid words out at an almost even pitch, which read
    # as a grid rather than a scattering.
    gap_min: int = 2
    gap_max: int = 7


@dataclass
class Beat:
    ripple_time: float = 0.55
    ripple_sigma: float = 2.2
    # Kick. Clamped to `ceil` where it is applied, so raising this makes more
    # cells reach the ceiling rather than pushing past it -- but past about 0.20
    # every rippled cell pins there and the ring flattens into a disc.
    ripple_lift: float = 0.20
    spark_time: float = 0.25
    # Snare. `spark_peak` replaces a cell's level rather than adding to it and
    # `reconcile` clamps it to `ceil`, so 0.58 is the whole of the available
    # headroom without giving up glow. `spark_frac` is the unconstrained lever:
    # it changes how many cells answer, not how bright they get.
    spark_peak: float = 0.58
    spark_frac: float = 0.075
    twinkle_frac_lo: float = 0.04
    twinkle_frac_hi: float = 0.11
    twinkle_decay: float = 0.22
    twinkle_lift: float = 0.20


# The loudness the gates below were tuned at: the 90th-percentile frame RMS of
# the benchmark track's instrumental, measured at 0.333. It is a constant here
# because it is a fact about a past measurement, not a setting.
REFERENCE_LEVEL = 0.333


@dataclass
class Analysis:
    """Gates on the audioAnalysis palette component that feeds `v6_aa`.

    These decide when a kick opens a ripple and a snare throws sparks, so they
    shape the beat response as directly as anything in `Beat` does. They were
    hand-tuned inside the .toe and existed nowhere in the repo until build.py
    needed to reproduce the network; the defaults are those tuned values.

    **They are absolute, and the component's input is the track.** Pushed
    unchanged they therefore mean something different on every master: a quiet
    one crosses none of them and gets no ripples and no sparks for the whole
    song, a loud one crosses them constantly. Nothing measured it, and the
    verifier could not see it either -- a field with no beat response is a
    perfectly bright field. `scaled()` is how they stop being one song's
    numbers; see `Track.level`.
    """
    kick_thresh: float = 0.209028
    snare_thresh: float = 0.311515
    rythm_thresh: float = 49.4591
    low_thresh: float = 0.1
    low_smooth: float = 0.0
    high_gain: float = 3.5
    low_lag_up: float = 0.08        # v8_low_lag, drives the glow's low-band term
    low_lag_dn: float = 0.22

    def scaled(self, level: float) -> dict:
        """These gates, adjusted for how loud this particular master is.

        Only the three that gate *events* move. `low_thresh`, `high_gain` and
        the lag times shape a continuous signal rather than deciding whether
        something happened, and scaling those would change the look rather than
        preserve it.

        The factor is clamped: a track four times louder than the reference
        should not get gates so high that nothing ever fires, and a nearly
        silent one should not get gates at zero, where every frame is a kick.
        """
        factor = 1.0
        if level and REFERENCE_LEVEL:
            factor = min(3.0, max(0.25, float(level) / REFERENCE_LEVEL))
        return {
            "kick_thresh": round(self.kick_thresh * factor, 6),
            "snare_thresh": round(self.snare_thresh * factor, 6),
            "rythm_thresh": round(self.rythm_thresh * factor, 6),
            "low_thresh": self.low_thresh,
            "low_smooth": self.low_smooth,
            "high_gain": self.high_gain,
            "factor": round(factor, 4),
        }


# Slider bounds and step per tunable: (min, max, step). These live with the
# parameters rather than in the UI, because the shell has no way to guess them --
# its fallback rescaled the maximum from whatever the current value happened to
# be, so a slider never settled in the same place twice, and clamped every
# minimum to zero, putting `offset` out of reach below 0.
RANGES: dict[str, tuple[float, float, float]] = {
    # grid
    "cols": (4, 64, 1), "vrows": (4, 64, 1), "band": (1, 64, 1),
    "letter_frac": (0.10, 0.50, 0.01),
    "band_top": (0, 8, 1), "font_px": (8, 200, 1),
    "width": (256, 3840, 2), "height": (256, 3840, 2),
    "glyph_aspect": (0.3, 1.5, 0.01),
    # look
    "dim_hue": (0, 1, 0.01), "dim_sat": (0, 1, 0.01),
    "level_min": (0, 1, 0.01), "level_max": (0, 1, 0.01), "ceil": (0, 1, 0.01),
    "drift_min": (0, 12, 0.1), "drift_max": (0, 12, 0.1), "dissolve": (0, 6, 0.1),
    "glow_base": (0, 2, 0.01), "glow_lfo": (0, 1, 0.01), "glow_low": (0, 1, 0.01),
    "glow_low_knee": (0.01, 2, 0.01), "glow_radius": (0, 80, 1),
    "glow_radius_lfo": (0, 40, 0.5), "glow_lfo_hz": (0, 0.5, 0.005),
    "bloom_size": (0, 60, 1), "bloom_bright": (0, 2, 0.01),
    # cueing
    "ramp_up": (0, 1, 0.01), "hold": (0, 3, 0.01), "ramp_dn": (0, 2, 0.01),
    "letter_spread": (0, 0.4, 0.01),
    "lead": (0, 2, 0.01), "offset": (-5, 5, 0.01),
    "stanza_size": (1, 12, 1), "ambient_target": (0, 500, 1),
    "ambient_cycle": (1, 20, 0.5), "gap_min": (0, 8, 1), "gap_max": (0, 10, 1),
    # beat
    "ripple_time": (0, 2, 0.01), "ripple_sigma": (0.2, 8, 0.1),
    "ripple_lift": (0, 1, 0.01), "spark_time": (0, 2, 0.01),
    "spark_peak": (0, 1, 0.01), "spark_frac": (0, 0.3, 0.005),
    "twinkle_frac_lo": (0, 0.4, 0.005), "twinkle_frac_hi": (0, 0.4, 0.005),
    "twinkle_decay": (0, 1, 0.01), "twinkle_lift": (0, 1, 0.01),
    # analysis
    "kick_thresh": (0, 1, 0.001), "snare_thresh": (0, 1, 0.001),
    "rythm_thresh": (0, 200, 0.1), "low_thresh": (0, 1, 0.01),
    "low_smooth": (0, 1, 0.01), "high_gain": (0, 10, 0.1),
    "low_lag_up": (0, 1, 0.01), "low_lag_dn": (0, 1, 0.01),
}


@dataclass
class Params:
    grid: Grid = field(default_factory=Grid)
    look: Look = field(default_factory=Look)
    cueing: Cueing = field(default_factory=Cueing)
    beat: Beat = field(default_factory=Beat)
    analysis: Analysis = field(default_factory=Analysis)

    def regions(self) -> dict[str, tuple[int, int, int, int]]:
        """Crops worth measuring separately in a rendered still, as (x, y, w, h).

        The band is where letters are allowed to land; everything below it must
        stay black. Leaving `band` at 14 of 24 rows put 480px of dead black at
        the bottom of frame for three versions, and a whole-frame average hid it
        every time -- which is why stills are measured per region, not globally.
        """
        g = self.grid
        y0 = int(g.band_top * g.height / g.vrows)
        y1 = int((g.band_top + g.band) * g.height / g.vrows)
        out = {"band": (0, y0, g.width, max(1, y1 - y0))}
        # Only report the area below the band when there actually is one.
        # `band == vrows - band_top` is legal and leaves nothing underneath, and
        # the clamped one-pixel crop it used to emit starts at the frame's
        # bottom edge -- ffmpeg rejects it, `region_stats` returns {}, and the
        # letters-below-the-band check silently becomes a no-op. That check
        # exists because letters escaping the band shipped three times.
        below = g.height - y1
        if below >= 2:
            out["lower"] = (0, y1, g.width, below)
        return out

    def validate(self) -> list[str]:
        out: list[str] = []
        g, lk, b, c = self.grid, self.look, self.beat, self.cueing

        if g.band > g.vrows - g.band_top:
            out.append(
                f"band {g.band} + band_top {g.band_top} exceeds vrows {g.vrows}; "
                "rows would fall outside the frame"
            )
        if g.band < g.vrows - g.band_top - 1:
            dead = (g.vrows - g.band_top - g.band) * (g.height / g.vrows)
            out.append(
                f"band {g.band} leaves {dead:.0f}px of dead space at the bottom of "
                f"frame (vrows {g.vrows}) — this shipped as a bug for three versions"
            )
        if lk.level_min >= lk.level_max:
            out.append("level_min must be below level_max")
        if lk.level_max > lk.ceil:
            out.append(f"level_max {lk.level_max} exceeds ceil {lk.ceil}")
        if b.spark_peak > lk.ceil:
            out.append(f"spark_peak {b.spark_peak} exceeds ceil {lk.ceil}")

        # the stacking check that actually caught the 0.99 regression
        stacked = lk.ceil + lk.glow_base * 0.55
        if stacked >= 0.95:
            out.append(
                f"ceil {lk.ceil} plus glow ~{lk.glow_base} will reach ≈{stacked:.2f} at "
                "the output — non-cued cells approach white and stop reading as dim"
            )
        if lk.glow_low_knee <= 0:
            out.append("glow_low_knee must be positive; it is a divisor")
        if lk.glow_radius - lk.glow_radius_lfo < 0:
            out.append(
                f"glow_radius {lk.glow_radius} minus its LFO swing "
                f"{lk.glow_radius_lfo} goes negative — blur size cannot"
            )
        if c.gap_min > c.gap_max:
            out.append("gap_min must not exceed gap_max")
        if c.ambient_target > g.band * g.cols * 0.9:
            out.append(
                f"ambient_target {c.ambient_target} is close to the {g.band * g.cols} "
                "cell capacity; layout will start failing to place lines"
            )
        return out


# ---------------------------------------------------------------- controls
#
# The 53 tunables above are the implementation. Showing all of them as sliders,
# labelled with the variable names they happen to have, is the same mistake the
# old Advanced panel made: `twinkle_frac_lo` and `rythm_thresh` are not choices
# anybody wants to make, and grouping them by the dataclass they live in is an
# accident of the code, not a way to think about how a video looks.
#
# What someone actually wants to move is small, and each thing moves several
# tunables at once. A control names the *effect*; the mapping below is how that
# effect is spelled in parameters. The full set stays reachable, because a
# specific fix sometimes needs a specific number.
#
# Each control interpolates its targets across a range chosen so that the whole
# span stays usable. `reconcile()` then enforces the relationships `validate()`
# checks, so a control cannot be dragged into an invalid config -- raising
# Brightness cannot push `level_max` past `ceil`.

@dataclass(frozen=True)
class Control:
    key: str
    label: str
    hint: str
    lead: str                                  # the target read back as position
    targets: dict[str, tuple[float, float]]    # "section.field": (at 0, at 1)


CONTROLS: tuple[Control, ...] = (
    Control(
        "brightness", "Brightness",
        "How strongly the whole field reads, lit words and ambient alike.",
        "look.level_max",
        {"look.level_min": (0.04, 0.16),
         "look.level_max": (0.22, 0.46),
         "look.ceil":      (0.44, 0.60)},
    ),
    Control(
        "colour", "Colour",
        "The hue of the unlit field, around the colour wheel: low is warm "
        "(red/orange), middle is cool (green/blue), high is violet.",
        "look.dim_hue",
        {"look.dim_hue": (0.0, 1.0)},
    ),
    Control(
        "motion", "Motion",
        "How restless the field is. Higher drifts and dissolves faster; "
        "lower is slower and calmer.",
        "look.drift_max",
        # Inverted on purpose: all three are *durations*. `drift_min`/`drift_max`
        # are the interval before a cell picks a new brightness target, and
        # `dissolve` is how long a word takes to fade. Longer means calmer, so
        # the busy end of this control is the low end of these numbers -- mapping
        # them the obvious way round made "more motion" settle the field down.
        {"look.drift_min": (6.0, 1.0),
         "look.drift_max": (12.0, 2.0),
         "look.dissolve":  (5.0, 1.0)},
    ),
    Control(
        "glow", "Glow",
        "The bloom around lit words — the difference between crisp and hazy.",
        "look.glow_base",
        {"look.glow_base":    (0.30, 0.75),
         "look.glow_radius":  (8.0, 34.0),
         "look.bloom_bright": (0.15, 0.55)},
    ),
    Control(
        "beat", "Beat response",
        "How visibly the field answers the drums: ripples, sparks, twinkle.",
        "beat.ripple_lift",
        {"beat.ripple_lift":  (0.0, 0.30),
         "beat.spark_peak":   (0.20, 0.58),
         "beat.twinkle_lift": (0.0, 0.40)},
    ),
    Control(
        "timing", "Word timing",
        "How long each word stays lit. Higher holds words longer and brings "
        "them in earlier.",
        "cueing.hold",
        {"cueing.ramp_up": (0.05, 0.25),
         "cueing.hold":    (0.35, 1.60),
         "cueing.ramp_dn": (0.10, 0.45),
         "cueing.lead":    (0.05, 0.35),
         "cueing.letter_spread": (0.0, 0.16)},
    ),
)


def _get(params: "Params", path: str) -> float:
    section, name = path.split(".")
    return float(getattr(getattr(params, section), name))


def _set(params: "Params", path: str, value: float) -> None:
    section, name = path.split(".")
    setattr(getattr(params, section), name, value)


def reconcile(params: "Params") -> None:
    """Nudge values back inside the relationships `validate()` insists on.

    A grouped control moves several parameters at once, and the constraints
    between them are not all expressible as per-slider bounds -- `ceil` and
    `glow_base` interact, and they belong to two different controls. Rather than
    refuse the edit, settle it: the invariants here are exactly the ones
    `validate()` reports, so after this it has nothing to say.
    """
    reconcile_look(params.look)
    b = params.beat
    b.spark_peak = min(b.spark_peak, params.look.ceil)


def reconcile_look(lk: "Look") -> None:
    """The rules that belong to the shared `Look` section alone.

    Separate from `reconcile` because more than one video type uses `Look` --
    they share the network and its glow chain -- but not every type has a
    `beat` section. Folding both into one function meant the beatsync type's
    reconcile reached for a section it does not have.
    """
    # Brightness and glow stack at the output; 0.99 measured there once, which
    # is how this check came to exist. Glow yields first, because the ceiling is
    # the more deliberate of the two -- but glow cannot go below zero, so a
    # ceiling that breaches the limit on its own has to come down as well.
    # Lowering only glow left `ceil = 1.0` still failing `validate()`, which
    # broke this function's own promise that afterwards there is nothing to say.
    if lk.ceil + lk.glow_base * 0.55 >= 0.95:
        lk.glow_base = max(0.0, round((0.94 - lk.ceil) / 0.55, 4))
    if lk.ceil + lk.glow_base * 0.55 >= 0.95:
        lk.ceil = round(0.94 - lk.glow_base * 0.55, 4)

    # After the ceiling settles, everything bounded by it follows.
    lk.level_max = min(lk.level_max, lk.ceil)
    lk.level_min = min(lk.level_min, lk.level_max - 0.02)
    lk.glow_radius_lfo = min(lk.glow_radius_lfo, lk.glow_radius)


def control_values(params: "Params") -> dict[str, float]:
    """Each control's position, 0..1, read back from its lead parameter."""
    out = {}
    for c in CONTROLS:
        lo, hi = c.targets[c.lead]
        v = (_get(params, c.lead) - lo) / (hi - lo) if hi != lo else 0.0
        out[c.key] = round(min(1.0, max(0.0, v)), 4)
    return out


def apply_control(params: "Params", key: str, value: float) -> dict[str, float]:
    """Move one control, returning the parameters it actually changed."""
    control = next((c for c in CONTROLS if c.key == key), None)
    if control is None:
        raise KeyError(f"no such control: {key}")
    v = min(1.0, max(0.0, float(value)))
    for path, (lo, hi) in control.targets.items():
        _set(params, path, round(lo + (hi - lo) * v, 4))
    reconcile(params)
    return {p: _get(params, p) for p in control.targets}


def controls_payload(params: "Params") -> list[dict]:
    """Everything the UI needs to draw the controls, values included."""
    now = control_values(params)
    return [{"key": c.key, "label": c.label, "hint": c.hint,
             "value": now[c.key], "drives": sorted(c.targets)}
            for c in CONTROLS]
