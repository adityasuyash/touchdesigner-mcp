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

from .._controls import Control, bind_controls


@dataclass
class Grid:
    cols: int = 24
    vrows: int = 24
    band: int = 22
    band_top: int = 1
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
class LyricGrid(Grid):
    """`Grid` plus the one thing only a renderer with words needs.

    `Grid` and `Look` describe the *network*, and all three video types share
    one network, so the beatsync types import them rather than copying them.
    But two of the values in them are read by this type's `field.py` alone --
    the share of the band a stanza may ask for, and how long a word takes to
    dissolve -- and a beatsync type that declared them would be offering two
    knobs that report success and change nothing. That is the failure mode the
    whole type system exists to prevent, so they live here instead.
    """
    # Share of the band's cells one stanza of lyrics may ask for. Letters sit on
    # every other cell along a continuous path, so the hard ceiling is about
    # half; contiguity costs more again, so the usable share is lower still.
    # Stanzas are grouped to fit this rather than to a fixed line count -- five
    # long lines wanted 488 of 528 cells, and the lines that would not place
    # were dropped, so their words were sung with nothing on screen to light.
    letter_frac: float = 0.28


@dataclass
class LyricLook(Look):
    """`Look` plus the three things only a renderer with words needs.

    `dissolve` is the word crossfade. `drift_min`/`drift_max` bound the interval
    before a *letter* picks a new brightness target -- there are no letters in a
    beatsync type, which declared both and read neither until the meta-test was
    tightened enough to notice.
    """
    dissolve: float = 2.5
    drift_min: float = 3.0
    drift_max: float = 6.0


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
    # Where a line of words SITS. For a long time there was exactly one answer
    # -- a snaking path from a random start -- so every lyric style, however it
    # was tinted or timed, was the same picture. This is the axis that makes two
    # looks read differently, and it was the one nobody could reach.
    #
    #   snake    a continuous path, wrapping (what it always did)
    #   rows     each line centred on its own row -- the classic lyric video
    #   columns  words running top to bottom, filling across
    #   scatter  every word its own block, no reading order
    layout: str = "snake"


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


@dataclass
class Backdrop:
    """What fills the space around the words.

    `lyric_grid` leaves roughly two thirds of the band black and nothing is
    allowed to draw there, even though the beat response -- `ripple`,
    `spark_env` -- is already computed over the whole grid every frame and then
    sampled only at cells that carry a letter. So the field answers the drums
    everywhere and shows it nowhere. This is that space.

    It is a section rather than a fourth video type for one reason that outweighs
    the rest: `Config.with_type` resets params to the new type's defaults and
    `Style.apply_to` refuses to cross types, so with a fourth type nobody could
    put a field behind their words without throwing away every `look`, `cueing`
    and `beat` value they had tuned for the song. Here they change one number.

    Everything is a weight, not a mode. An enum would have been unreachable from
    the browser -- the settings panel skips any tunable that is not a number
    (`index.html`, `typeof v !== 'number'`) -- and invisible to `describe.py`,
    which only ever proposes floats. So "no backdrop" is `back_level = 0`, a
    sweeping crest is `back_wave`, a breathing field is `back_swell`, and the
    two compose instead of excluding each other.

    `back_level = 0` is the default and means the renderer draws exactly what it
    drew before this section existed -- including making no random draws at all,
    which matters because one shared generator lays out the stanzas.

    Every field is prefixed `back_` because `Config.as_params` flattens every
    section AND the track into one dict for TouchDesigner, so the whole program
    shares one namespace with no sections in it. The unprefixed `level` this
    section first declared was silently overwritten by `track.level` -- the
    measured loudness of the master, 0.42 against the 0.05 meant here -- which
    would have pushed the backdrop brighter than the words it sits behind, with
    nothing reporting anything. A prefix makes that impossible rather than
    merely absent today.
    """
    back_level: float = 0.0      # master: 0 draws no backdrop and no randomness
    back_lift: float = 0.045     # how far the beat swings it
    back_wave: float = 0.0       # a crest crossing the field on the beat grid
    back_swell: float = 0.0      # coverage thickening on the downbeat
    # The drums, each with its own weight. These did not exist, and the kick was
    # normalised by the LETTERS' ripple_lift -- so every beatsync style got the
    # same kick amplitude and five looks collapsed into about three.
    back_kick: float = 1.0
    back_snare: float = 1.0
    back_high: float = 0.0
    # Its own colour, so it reads as behind the words rather than beside them.
    back_hue: float = 0.58
    back_sat: float = 0.20
    back_density: float = 0.55   # share of free cells carrying a glyph
    back_glyphs: str = ".:-=+*#"  # lightest to heaviest; `back_swell` steps it
    back_beats: float = 4.0      # beats for one pass across the field
    back_width: float = 3.5      # thickness of the crest, in cells
    back_vertical: bool = False  # travel down instead of across
    back_attack: float = 0.14    # `back_swell`: share of the bar spent opening
    back_reroll: float = 16.0    # seconds between re-scattering the field


# The four things the "Behind the words" row offers, as presets over the numbers
# above rather than as an enum -- so every one of them stays reachable from a
# slider and from a written description.
def can_back_words(source) -> bool:
    """Can this renderer's look sit BEHIND lyric_grid's words?

    Only if it draws into the same character field, which is exactly what a
    `pulse` or `swell` section means. `rings`, `strata` and `scope` have their
    own networks -- there is no sense in which their picture can become the
    ambient layer of somebody else's grid, and offering it would put a choice
    in the gallery that cannot render.

    This was free to assume while every beatsync type WAS the grid. It is the
    kind of assumption that survives right up until it is wrong.
    """
    return bool(getattr(source, "pulse", None) or getattr(source, "swell", None))


def backdrop_from(params: "Params", source) -> list[str]:
    """Set the backdrop from a beatsync renderer's own parameters.

    `source` is another type's `Params` -- `pulse_grid`'s or `swell`'s -- or
    None for no backdrop at all. Returns whatever had to be pulled in to fit,
    so the run can say so: a look silently rendered at half strength is the
    defect class this project keeps closing.

    A beatsync style is tuned to be the WHOLE picture. Behind words it cannot
    be, so its levels are rescaled rather than copied -- but the RATIOS between
    its sweep, kick, snare and hat response are kept, because those ratios are
    what make one style read differently from another. Copying them flat is how
    five looks collapsed into three.

    Its colour comes with it: Heartbeat stays warm red behind cool blue words,
    so the tile you clicked is what lands on screen.
    """
    bd, lk = params.backdrop, params.look
    if source is None:
        bd.back_level = 0.0
        bd.back_wave = bd.back_swell = 0.0
        return []

    beat = getattr(source, "pulse", None) or getattr(source, "swell", None)
    look = getattr(source, "look", None)
    if beat is None:
        return ["that renderer has no beat section to read"]

    if look is not None:
        bd.back_hue, bd.back_sat = look.dim_hue, look.dim_sat

    # The band the backdrop is allowed to occupy is the one the ambient
    # decoration it replaces has always used -- level_min..level_max, legible
    # behind lit words by construction. Bounding it below level_min instead was
    # my own invention and cost a 6.4:1 beat ratio to get 2:1.
    floor, ceiling = lk.level_min, lk.level_max
    span = max(0.01, ceiling - floor)

    # Every drive the source expresses, on its own scale, so the ratios survive.
    drives = {
        "wave": float(getattr(beat, "wave_lift", getattr(beat, "back_wave", 0.0))
                      or getattr(beat, "open_max", 0.0) - getattr(beat, "open_min", 0.0)),
        "kick": float(getattr(beat, "kick_lift", getattr(beat, "kick_open", 0.0))),
        "snare": float(getattr(beat, "snare_peak", getattr(beat, "snare_frac", 0.0))),
        "high": float(getattr(beat, "high_lift", getattr(beat, "high_grain", 0.0))),
    }
    loudest = max(drives.values()) or 1.0

    bd.back_level = round(floor, 4)
    bd.back_lift = round(span, 4)
    bd.back_wave = round(min(1.0, drives["wave"] / loudest), 4)
    bd.back_swell = round(min(1.0, (getattr(beat, "open_max", 0.0)
                                    - getattr(beat, "open_min", 0.0)) / loudest), 4)
    bd.back_kick = round(min(1.0, drives["kick"] / loudest), 4)
    bd.back_snare = round(min(1.0, drives["snare"] / loudest), 4)
    bd.back_high = round(min(1.0, drives["high"] / loudest), 4)

    for name, src in (("back_density", "density"), ("back_glyphs", "glyphs"),
                      ("back_beats", "wave_beats"), ("back_width", "wave_width"),
                      ("back_vertical", "vertical"), ("back_attack", "attack"),
                      ("back_reroll", "reroll")):
        if hasattr(beat, src):
            setattr(bd, name, getattr(beat, src))
    if hasattr(beat, "bar_beats"):
        bd.back_beats = beat.bar_beats

    wanted = {"back_density": bd.back_density, "back_level": bd.back_level,
              "back_lift": bd.back_lift}
    reconcile(params)
    clamped = []
    for key, was in wanted.items():
        now = getattr(bd, key)
        if abs(now - was) > 1e-4:
            clamped.append(f"{key} pulled from {was:.3f} to {now:.3f} so the "
                           "words stay readable")
    return clamped


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
    # `kick_thresh`, `snare_thresh`, `rythm_thresh` and `high_gain` used to live
    # here. They gated the palette component's kick, snare, rythm and high
    # channels -- and when the drum response moved to the onset table pushed in
    # from the repo, the network stopped selecting any of those channels. Only
    # `low` is taken (`v8_low`), so four knobs were being scaled, pushed and
    # reported as applied while moving nothing at all: offered, pushed, ignored.
    low_thresh: float = 0.1
    low_smooth: float = 0.0
    low_lag_up: float = 0.08        # v8_low_lag, drives the glow's low-band term
    low_lag_dn: float = 0.22

    def scaled(self, level: float) -> dict:
        """These gates, adjusted for how loud this particular master is.

        Nothing here gates an *event* any more -- the drums come from the onset
        table, measured offline -- so nothing is scaled by the factor today.
        The factor is still reported, because it is the number that says how
        far this master sits from the reference and the builder logs it.

        It is clamped: a track four times louder than the reference should not
        get gates so high that nothing fires, and a nearly silent one should
        not get gates at zero, where every frame is a kick.
        """
        factor = 1.0
        if level and REFERENCE_LEVEL:
            factor = min(3.0, max(0.25, float(level) / REFERENCE_LEVEL))
        return {
            "low_thresh": self.low_thresh,
            "low_smooth": self.low_smooth,
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
    # backdrop -- all prefixed, see the dataclass for why
    "back_level": (0, 0.3, 0.005), "back_lift": (0, 0.3, 0.005),
    "back_wave": (0, 1, 0.01), "back_swell": (0, 1, 0.01),
    "back_kick": (0, 1, 0.01), "back_snare": (0, 1, 0.01),
    "back_high": (0, 1, 0.01),
    "back_hue": (0, 1, 0.01), "back_sat": (0, 1, 0.01),
    "back_density": (0.05, 1.0, 0.01),
    "back_beats": (0.5, 16, 0.5), "back_width": (0.5, 12, 0.1),
    "back_attack": (0.02, 0.9, 0.01), "back_reroll": (1, 60, 1),
    # analysis
    "low_thresh": (0, 1, 0.01), "low_smooth": (0, 1, 0.01),
    "low_lag_up": (0, 1, 0.01), "low_lag_dn": (0, 1, 0.01),
}


@dataclass
class Params:
    grid: LyricGrid = field(default_factory=LyricGrid)
    look: LyricLook = field(default_factory=LyricLook)
    cueing: Cueing = field(default_factory=Cueing)
    beat: Beat = field(default_factory=Beat)
    backdrop: Backdrop = field(default_factory=Backdrop)
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
        bd = self.backdrop

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
        if c.layout not in {k for k, _ in LAYOUTS}:
            out.append(
                f"layout {c.layout!r} is not one of "
                f"{', '.join(k for k, _ in LAYOUTS)}")
        if c.gap_min > c.gap_max:
            out.append("gap_min must not exceed gap_max")
        if c.ambient_target > g.band * g.cols * 0.9:
            out.append(
                f"ambient_target {c.ambient_target} is close to the {g.band * g.cols} "
                "cell capacity; layout will start failing to place lines"
            )

        # ---- the backdrop may not outshine the words it sits behind ----
        #
        # The bound is the band the AMBIENT DECORATION occupies, because that is
        # what the backdrop replaces and it has always been legible behind lit
        # words. Holding it under `level_min` instead -- an earlier invention of
        # mine -- bought nothing and cost a great deal: it allowed a 2:1 beat
        # ratio where the styles being mapped in run 6.4:1, and its knock-on
        # density cap thinned four of the five shipped looks.
        peak = bd.back_level + bd.back_lift
        if bd.back_level > 0.0 and peak > lk.level_max:
            out.append(
                f"backdrop peaks at {peak:.3f}, above level_max {lk.level_max} — "
                "it would be brighter than any unlit letter and the words would "
                "stop reading as the subject"
            )
        if bd.back_level < 0.0:
            out.append("back_level cannot be negative")
        if not (0.0 < bd.back_density <= 1.0):
            out.append(f"back_density {bd.back_density} must be above 0 and at most 1")
        if bd.back_beats <= 0:
            out.append("back_beats must be positive; it divides the beat period")
        if not (0.0 < bd.back_attack < 1.0):
            out.append(
                f"back_attack {bd.back_attack} must be a share of the bar, above 0 "
                "and below 1")
        if not bd.back_glyphs:
            out.append("back_glyphs cannot be empty; there would be nothing to draw")
        return out

    def notes(self) -> list[str]:
        """True things worth saying that are not faults.

        `validate()` means "this render cannot be trusted" and blocks a push.
        Words alone on black is unusual but it is a choice somebody can make on
        purpose -- it is what the None backdrop is FOR -- so it belongs here.
        Putting it in `validate()` made the one preset that expresses it
        impossible to apply.
        """
        out: list[str] = []
        if self.cueing.ambient_target == 0 and self.backdrop.back_level <= 0.0:
            out.append(
                "nothing is drawn between the words, so every lyric gap and the "
                "whole outro will be black"
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

LAYOUTS: tuple[tuple[str, str], ...] = (
    ("snake", "a continuous path that wraps through the field"),
    ("rows", "each line centred on its own row"),
    ("columns", "words running top to bottom"),
    ("scatter", "every word its own block, anywhere"),
)


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


def reconcile(params: "Params") -> None:
    """Nudge values back inside the relationships `validate()` insists on.

    A grouped control moves several parameters at once, and the constraints
    between them are not all expressible as per-slider bounds -- `ceil` and
    `glow_base` interact, and they belong to two different controls. Rather than
    refuse the edit, settle it: the invariants here are exactly the ones
    `validate()` reports, so after this it has nothing to say.
    """
    reconcile_look(params.look)
    lk, b, bd = params.look, params.beat, params.backdrop
    b.spark_peak = min(b.spark_peak, lk.ceil)

    # Bounded by `level_max`, which the Brightness control moves, so this has to
    # run AFTER `reconcile_look` has settled the look or Brightness at its
    # lowest leaves a config `validate()` rejects. The backdrop gives way, never
    # the words.
    bd.back_level = max(0.0, min(bd.back_level, round(lk.level_max, 4)))
    bd.back_lift = max(0.0, min(bd.back_lift,
                                round(lk.level_max - bd.back_level, 4)))
    bd.back_density = min(1.0, max(0.05, bd.back_density))
    bd.back_beats = max(0.5, bd.back_beats)
    bd.back_attack = min(0.9, max(0.02, bd.back_attack))


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


# Bound to this type's own controls and its own `reconcile`; the
# machinery itself is shared, because it was identical in every type.
control_values, apply_control, controls_payload = bind_controls(
    CONTROLS, reconcile)
