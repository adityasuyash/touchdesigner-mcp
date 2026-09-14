"""Author the shipped beatsync styles, and render whatever preview is missing.

The gallery is how a renderer gets chosen, and a renderer with no styles shows
one bare "Built-in" tile next to a lyric row full of looks -- which reads as
unfinished rather than as a choice. These are the five looks for `pulse_grid`.

They are written from the type's own defaults with a small, deliberate delta
each, rather than by hand in TOML: the defaults move over time, and a style file
that was hand-copied from them silently becomes a snapshot of an older renderer.

    python scripts/seed_styles.py            # write the style files
    python scripts/seed_styles.py --preview  # ... and record any missing preview

Previews need TouchDesigner up with a song's project open, because a beat
renderer previewed against a neutral 120bpm fallback is showing its timing
against nothing. The song's own look and words are pushed back afterwards.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lyricfield import styles as styles_mod           # noqa: E402
from lyricfield import types as types_mod             # noqa: E402

# Backdrop previews are not styles; see `backdrop_previews`.
BACKDROP_ROOT = styles_mod.DEFAULT_ROOT / "_backdrops"
# Each renderer's own defaults, so the "Built-in" tiles are not the only ones in
# the gallery showing "no preview yet".
BUILTIN_ROOT = styles_mod.DEFAULT_ROOT / "_builtin"

# (type, name, description, {section.field: value})
LOOKS: list[tuple[str, str, str, dict]] = [
    # ---------------------------------------------------------- monument
    # One word, filling the frame. The two looks pull the same renderer in
    # opposite directions: struck hard and cut clean, or held and breathing.

    # ---------------------------------------------------------- window

    # ---------------------------------------------------------- orbit
    ("orbit", "Ring",
     "the line carried round a slowly turning circle",
     {"path.shape": "circle", "path.radius": 0.4, "path.spin": 0.045,
      "path.spread": 0.03, "line.size": 54.0,
      "look.hue": 0.75, "look.sat": 0.45, "look.glow": 0.34}),
    ("orbit", "Undertow",
     "the line riding a slow travelling wave, read left to right",
     {"path.shape": "wave", "path.radius": 0.26, "path.spin": 0.1,
      "path.twist": 2.2, "line.size": 60.0,
      "look.hue": 0.5, "look.sat": 0.5, "look.glow": 0.4,
      "beat.kick_push": 0.2}),

    # ---------------------------------------------------------- swarm

    # ---------------------------------------------------------- horizon
    ("horizon", "Sunset",
     "a wide low sun over a slow grid",
     {"ground.horizon": 0.58, "ground.rungs": 9.0, "ground.lanes": 13.0,
      "ground.speed": 0.3, "sun.radius": 0.42, "sun.rise": 0.1,
      "sun.bands": 7.0, "line.size": 78.0,
      "look.hot": 0.94, "look.cold": 0.55, "look.sky": 0.4}),
    ("horizon", "Runway",
     "a dense grid rushing past a small high sun",
     {"ground.horizon": 0.42, "ground.rungs": 22.0, "ground.lanes": 26.0,
      "ground.speed": 1.2, "ground.weight": 0.035,
      "sun.radius": 0.17, "sun.rise": 0.3, "sun.bands": 13.0,
      "line.size": 66.0, "line.line_y": 0.2,
      "look.hot": 0.85, "look.cold": 0.45, "look.sky": 0.2,
      "beat.kick_lift": 0.55}),

    # ---------------------------------------------------------- rings
    ("rings", "Sonar",
     "slow wide rings on a dark field, a long way apart",
     {"ring.speed": 0.3, "ring.thick": 0.014, "ring.birth": 0.95,
      "ring.decay": 2.0, "spoke.peak": 0.2, "grain.lift": 0.05,
      "look.hue": 0.48, "look.sat": 0.6, "look.core": 0.1,
      "look.glow": 0.5, "look.bloom": 26.0}),
    ("rings", "Bloom",
     "thick fast rings over a bright core, crowding each other",
     {"ring.speed": 1.15, "ring.thick": 0.075, "ring.birth": 0.6,
      "ring.decay": 0.7, "spoke.peak": 0.6, "spoke.count": 22,
      "grain.lift": 0.24, "grain.freq": 70.0,
      "look.hue": 0.08, "look.sat": 0.5, "look.core": 0.3,
      "look.glow": 0.25, "look.bloom": 10.0}),

    # ---------------------------------------------------------- strata
    ("strata", "Ledger",
     "many thin bands, struck quietly and often",
     {"band.count": 20, "band.gap": 0.42, "band.rest": 0.05,
      "band.lit": 0.6, "band.decay": 0.2, "band.walk": 1,
      "shear.amount": 0.05, "flicker.lift": 0.06,
      "look.hue": 0.52, "look.sat": 0.3, "look.glow": 0.08}),
    ("strata", "Slab",
     "few heavy bands, struck hard and sheared wide",
     {"band.count": 5, "band.gap": 0.1, "band.rest": 0.14,
      "band.lit": 0.97, "band.decay": 0.75, "band.walk": 2,
      "shear.amount": 0.34, "shear.snap": 0.5,
      "flicker.lift": 0.2, "flicker.rows": 17.0,
      "look.hue": 0.03, "look.sat": 0.7, "look.glow": 0.2,
      "look.bloom": 12.0}),

    # ---------------------------------------------------------- scope

    # The lyric look. It has to be *distinct from the defaults*, or the gallery
    # shows two tiles for one look: when the built-in timing was tuned it was
    # tuned to match this file exactly, and the style quietly became a copy of
    # the thing it sits next to. Calm means calmer than the default, not equal
    # to it -- longer dissolve, slower drift, softer beat.

    # The beatsync looks, rebuilt. The old five measured as about two and a
    # half distinguishable pictures: cascade and shimmer correlated at 0.82,
    # sweep and cascade at 0.62, and the differences were mostly density and
    # hue rather than behaviour. They were also timid -- every one sat at the
    # type's default level_min/level_max/ceil and at the DEFAULT of all nine
    # glow and bloom values, and none had moved `lit_at`, which is the single
    # strongest control in the renderer: it is the hard threshold where a cell
    # leaves the dim layer for the bold one, gaining the white alpha channel,
    # the bold typeface and a tight bloom all at once.
    #
    # The recipe, measured rather than guessed: a DARK, sparse baseline so the
    # base never approaches the threshold, a HIGH `lit_at`, and LARGE lifts.
    # Raising the lifts alone just promotes more of the field and flattens it;
    # lowering the floor and raising the threshold at the same time is what
    # turns promotion back into an event.

    # Lyric looks that differ STRUCTURALLY, not just in tint. Each picks a
    # different arrangement -- where the words sit was the axis no style could
    # reach, which is why more presets could never have answered "more styles".
    ("lyric_grid", "Marquee",
     "each line centred on its own row — the most readable of the set",
     {"cueing.layout": "rows", "cueing.gap_min": 1, "cueing.gap_max": 3,
      "cueing.hold": 1.10, "cueing.ramp_up": 0.08, "cueing.ramp_dn": 0.30,
      "cueing.letter_spread": 0.04, "cueing.ambient_target": 90,
      "look.dim_hue": 0.60, "look.dim_sat": 0.22, "look.dissolve": 1.8,
      "look.drift_min": 5.0, "look.drift_max": 10.0,
      "look.glow_base": 0.44, "look.glow_radius": 12.0,
      "look.bloom_bright": 0.50, "look.bloom_size": 7.0}),


    ("lyric_grid", "Ticker",
     "words running top to bottom, tight and mechanical",
     {"cueing.layout": "columns", "cueing.gap_min": 1, "cueing.gap_max": 4,
      "cueing.hold": 0.55, "cueing.ramp_up": 0.03, "cueing.ramp_dn": 0.08,
      "cueing.letter_spread": 0.0, "cueing.ambient_target": 150,
      "look.dim_hue": 0.33, "look.dim_sat": 0.45, "look.dissolve": 0.8,
      "look.drift_min": 1.0, "look.drift_max": 2.5,
      "look.glow_base": 0.32, "look.glow_radius": 8.0,
      "look.bloom_bright": 0.25, "look.bloom_size": 5.0}),

    ("lyric_grid", "Static",
     "words surfacing out of a dense restless field, each on its own",
     {"cueing.layout": "scatter", "cueing.hold": 0.90,
      "cueing.ramp_up": 0.05, "cueing.ramp_dn": 0.20,
      "cueing.letter_spread": 0.15, "cueing.ambient_target": 300,
      "look.dim_hue": 0.72, "look.dim_sat": 0.15,
      "look.level_min": 0.06, "look.level_max": 0.30,
      "look.dissolve": 1.2, "look.drift_min": 0.8, "look.drift_max": 2.0,
      "look.glow_base": 0.38, "look.glow_radius": 14.0,
      "look.bloom_bright": 0.45,
      "beat.spark_frac": 0.12, "beat.spark_peak": 0.55}),



    ("pulse_grid", "Heartbeat",
     "no sweep at all — the kick is the entire picture, wide and slow",
     {"look.dim_hue": 0.02, "look.dim_sat": 0.72,
      "look.level_min": 0.03, "look.level_max": 0.18, "look.ceil": 0.56,
      "look.glow_base": 0.60, "look.glow_radius": 26.0, "look.bloom_bright": 0.55,
      "look.bloom_size": 14.0,
      "pulse.wave_beats": 8.0, "pulse.wave_width": 6.0, "pulse.wave_lift": 0.05,
      "pulse.lit_at": 0.52, "pulse.density": 0.55,
      "pulse.kick_lift": 0.85, "pulse.kick_time": 0.90, "pulse.kick_sigma": 5.0,
      "pulse.snare_peak": 0.30, "pulse.snare_frac": 0.03,
      "pulse.high_lift": 0.04, "pulse.reroll": 12.0,
      "pulse.glyphs": ".oO0@",
      "grid.cols": 18}),


    ("pulse_grid", "Constellation",
     "nearly black, crossed very slowly — a few points, held a long time",
     # Deliberately NOT kick-led. Measured against Heartbeat it correlated at
     # 0.93 when both led with the kick: same behaviour, different density and
     # hue, which is the trap the whole rebuild is meant to escape. Its identity
     # is a slow wide crest through an almost empty field, so the crest leads
     # and the kick is a punctuation.
     {"look.dim_hue": 0.68, "look.level_min": 0.02, "look.level_max": 0.14,
      "look.glow_base": 0.62, "look.glow_radius": 32.0, "look.bloom_bright": 0.55,
      "look.bloom_size": 18.0,
      "pulse.wave_beats": 16.0, "pulse.wave_width": 8.0, "pulse.wave_lift": 0.68,
      "pulse.lit_at": 0.80, "pulse.density": 0.18, "pulse.glyphs": ".,+x*",
      "pulse.kick_lift": 0.22, "pulse.kick_time": 0.90, "pulse.kick_sigma": 3.0,
      "pulse.snare_peak": 0.35, "pulse.snare_frac": 0.03,
      "pulse.high_lift": 0.06, "pulse.reroll": 45.0,
      "grid.cols": 28,
      "look.dim_sat": 0.55}),

    ("pulse_grid", "Shimmer",
     "a dense wall with no sweep; the hats and the snare carry all of it",
     {"look.dim_hue": 0.50, "look.dim_sat": 0.3,
      "look.level_min": 0.06, "look.level_max": 0.26,
      "look.glow_base": 0.34, "look.glow_radius": 8.0, "look.bloom_bright": 0.30,
      "pulse.wave_beats": 4.0, "pulse.wave_width": 3.5, "pulse.wave_lift": 0.04,
      "pulse.lit_at": 0.58, "pulse.density": 0.95,
      "pulse.kick_lift": 0.15,
      "pulse.snare_peak": 0.80, "pulse.snare_frac": 0.18, "pulse.snare_time": 0.16,
      "pulse.high_lift": 0.70, "pulse.high_time": 0.34, "pulse.reroll": 5.0,
      "pulse.glyphs": "`'^*+x",
      "grid.cols": 36}),

    # `swell` shipped with NO styles at all -- a whole renderer with no tile to
    # pick. It expresses the beat as coverage rather than light, so its
    # brightness cannot exceed level_max and it has no stacking problem; what
    # makes a swell look pronounced is the coverage swing and the glyph ramp.
    # It is also the only type that reads kick_in / high_in / duration, so it
    # is the only one with a beginning, an arrival and an ending.
    ("swell", "Tide",
     "the field breathes — wide and slow, thickening on the downbeat",
     {"look.dim_hue": 0.56, "look.level_min": 0.06, "look.level_max": 0.42,
      "look.glow_base": 0.55, "look.glow_radius": 24.0, "look.bloom_bright": 0.45,
      "swell.bar_beats": 8.0, "swell.attack": 0.22,
      "swell.open_min": 0.06, "swell.open_max": 0.96, "swell.lit_at": 0.72,
      "swell.kick_open": 0.55, "swell.snare_frac": 0.10,
      "swell.high_grain": 0.30, "swell.outro": 18.0,
      "swell.glyphs": "~-=+#",
      "grid.cols": 22,
      "look.dim_sat": 0.6}),

    ("swell", "Stutter",
     "short, hard breaths — a fast bar with a near-instant attack",
     {"look.dim_hue": 0.12, "look.dim_sat": 0.5,
      "look.level_min": 0.04, "look.level_max": 0.38,
      "look.glow_base": 0.36, "look.glow_radius": 9.0, "look.bloom_bright": 0.52,
      "swell.bar_beats": 1.0, "swell.attack": 0.05,
      "swell.open_min": 0.02, "swell.open_max": 0.88, "swell.lit_at": 0.60,
      "swell.glyphs": "_-=#", "swell.kick_open": 0.70,
      "swell.snare_frac": 0.14, "swell.snare_time": 0.16,
      "swell.high_grain": 0.45, "swell.reroll": 6.0,
      "grid.cols": 16}),

    # ------------------------------------------------------- approach
    # From the Chainsmokers' "Closer": the lyrics travelling through 3D space.
    # The two styles are the two readings of that -- a slow drift out of the
    # dark, and a hard rush past the camera.


    # --------------------------------------------------------- glitch
    ("glitch", "Dropout",
     "a clean signal that tears wide open on the beat",
     {"tear.rest": 0.01, "tear.throw": 0.2, "tear.band": 0.09,
      "tear.kick_lift": 0.85, "tear.churn": 14.0,
      "split.gap": 0.001, "split.snare_lift": 0.045,
      "lines.count": 150.0, "lines.depth": 0.2, "lines.roll": 90.0,
      "lines.hat_lift": 0.3,
      "stage.size": 92.0,
      "look.hue": 0.52, "look.sat": 0.08, "look.glow": 0.36,
      "look.bloom": 16.0}),

    ("glitch", "Bleed",
     "permanently damaged — heavy scanlines and channels far apart",
     {"tear.rest": 0.22, "tear.throw": 0.05, "tear.band": 0.025,
      "tear.kick_lift": 0.3, "tear.churn": 26.0,
      "split.gap": 0.014, "split.snare_lift": 0.02,
      # 420 lines over a 1280-high frame is three pixels each, which no
      # player and no preview can resolve -- downscaled, the dark lines average
      # into the glyph cores and the type stops reaching the bold layer at all
      # (measured: a peak of 0.72 against the 0.78 a lit word has to clear).
      # Coarser and deeper reads heavier, not lighter.
      "lines.count": 170.0, "lines.depth": 0.6, "lines.roll": -20.0,
      "lines.hat_lift": 0.15,
      "stage.size": 64.0, "stage.hold": 3.4,
      "look.hue": 0.86, "look.sat": 0.35, "look.floor": 0.04,
      "look.glow": 0.22, "look.bloom": 7.0}),

    # ------------------------------------------------------- halftone
    ("halftone", "Newsprint",
     "a fine grey screen, the way a photograph prints in a paper",
     {"screen.pitch": 90.0, "screen.angle": 45.0, "screen.dot": 0.66,
      "screen.soft": 0.09,
      "ink.separate": False, "ink.hue": 0.1, "ink.sat": 0.05,
      "tone.base": 0.06, "tone.kick_lift": 0.7, "tone.snare_lift": 0.35,
      "tone.hat_lift": 0.06, "tone.wave": 0.1, "tone.vignette": 0.7,
      "look.glow": 0.12, "look.bloom": 5.0}),

    ("halftone", "Rosette",
     "three coarse screens at printer's angles, beating into a rosette",
     {"screen.pitch": 26.0, "screen.angle": 15.0, "screen.dot": 0.7,
      "screen.soft": 0.16,
      "ink.separate": True, "ink.spread": 30.0, "ink.hue": 0.02,
      "ink.sat": 0.5,
      "tone.base": 0.14, "tone.kick_lift": 0.6, "tone.snare_lift": 0.4,
      "tone.hat_lift": 0.1, "tone.wave": 0.1, "tone.vignette": 0.35,
      "look.glow": 0.4, "look.bloom": 18.0}),

    # ------------------------------------------------------- spectrum
    ("spectrum", "Analyser",
     "the classic: tall thin bars off the floor, with peak caps",
     {"bars.count": 40, "bars.fill": 0.55, "bars.reach": 0.72,
      "bars.floor_at": 0.94, "bars.mirror": False, "bars.settle": 0.28,
      "caps.on": True, "caps.thick": 0.005, "caps.fall": 0.4,
      "caps.hang": 0.3,
      "look.hue": 0.45, "look.hue_span": 0.4, "look.sat": 0.7,
      "look.glow": 0.3, "look.bloom": 11.0}),

    ("spectrum", "Equaliser",
     "few wide bars mirrored about the middle, fast and heavy",
     {"bars.count": 12, "bars.fill": 0.82, "bars.reach": 0.42,
      "bars.floor_at": 0.5, "bars.mirror": True, "bars.settle": 0.08,
      "caps.on": False, "caps.thick": 0.008, "caps.fall": 1.2,
      "caps.hang": 0.1,
      "look.hue": 0.92, "look.hue_span": 0.12, "look.sat": 0.45,
      "look.floor": 0.03, "look.glow": 0.5, "look.bloom": 22.0}),
]


def build_styles() -> list[styles_mod.Style]:
    import importlib
    out = []
    for slug, name, why, deltas in LOOKS:
        P = importlib.import_module(f"lyricfield.types.{slug}.params")
        params = types_mod.get_type(slug).default_params()
        for path, value in deltas.items():
            section, field = path.split(".")
            target = getattr(params, section, None)
            if target is None or not hasattr(target, field):
                raise KeyError(f"{name}: {slug} has no {path}")
            setattr(target, field, value)
        P.reconcile(params)
        problems = params.validate()
        if problems:
            raise ValueError(f"{name} is not a valid {slug} config: {problems}")
        out.append(styles_mod.Style(
            name=name, slug=styles_mod.slugify(name), type=slug,
            description=why,
            created=styles_mod.datetime.now(styles_mod.timezone.utc)
            .isoformat(timespec="seconds"),
            params=params))
    return out


def builtin_previews(client, live, moments_for, force=False,
                     root=styles_mod.DEFAULT_ROOT) -> list[str]:
    """One capture per RENDERER, of its own defaults.

    The gallery synthesises a "Built-in" tile per registered type and hardcoded
    `has_preview: false`, so Lyric grid, Pulse grid and Swell have never shown
    anything — the three tiles that introduce the three renderers were the three
    with nothing to look at.

    Not styles: no `style.toml`, so `_style_dirs` skips them, and they live
    beside `_backdrops` under the same served mount.
    """
    from lyricfield import styles as S

    # Only for a renderer that ships no looks of its own. A look is a preset of
    # its renderer, so a renderer with looks would appear in the gallery twice
    # as near-identical pictures -- Approach beside Corridor and Flyby, Orbit
    # beside Ring. Where there are looks, those ARE the renderer's tiles.
    owned = {st.type for st in S.list_styles(root)}

    failed = []
    for vt in types_mod.list_types():
        if vt.slug in owned:
            continue
        draft = S.Style(name=vt.name, slug=vt.slug, type=vt.slug,
                        description=vt.description,
                        params=vt.default_params())
        if not force and draft.preview_is_current(BUILTIN_ROOT):
            print(f"{vt.name} (built-in): preview already matches this look")
            continue
        for at in moments_for(vt.family):
            print(f"{vt.name} (built-in): recording from {at:.1f}s")
            try:
                S.capture_preview(client, draft, at=at, seconds=4.0,
                                  root=BUILTIN_ROOT, live=live,
                                  progress=lambda m: print("   ", m))
                break
            except S.StillPreview as e:
                print(f"    {e}")
            except S.FallbackPreview as e:
                # Not worth another moment: the picture would be the same
                # defaults at every one of them. Recorded as a failure here
                # rather than left to the for-else, which this break skips.
                print(f"    {e}")
                failed.append(f"{vt.name} (built-in)")
                break
        else:
            failed.append(f"{vt.name} (built-in)")
    return failed


def backdrop_previews(client, live, root, moments, force=False) -> list[str]:
    """One capture per beatsync look, as it appears BEHIND WORDS.

    Its own preview will not do. `styles/pulse_grid/heartbeat/preview.mp4` was
    captured with that style as the whole picture, at a peak and a density it
    is not allowed behind lyrics -- so the tile would promise something the
    render cannot deliver, which is the same class of lie as a still preview of
    a moving style.

    These are not styles: they set a handful of one type's tunables and have no
    `style.toml`. They live under `styles/_backdrops/<lyric>/<beat>/<slug>/`,
    existing /styles mount serves, the `!styles/**/preview.mp4` negation tracks,
    and `_style_dirs` skips because it yields only folders holding a style file.
    """
    import importlib

    from lyricfield import styles as S

    lyric = types_mod.get_type(types_mod.DEFAULT_TYPE)
    P = importlib.import_module(f"lyricfield.types.{lyric.slug}.params")
    if not hasattr(P, "backdrop_from"):
        return []

    failed = []
    for st in S.list_styles():
        vt = types_mod.get_type(st.type)
        if vt.family != types_mod.BEATSYNC:
            continue
        # Only the looks that share the grid's own field can become the layer
        # behind words. A renderer with its own network cannot be somebody
        # else's ambient layer, and a preview of that would be a promise the
        # run could not keep.
        if not P.can_back_words(st.params):
            print(f"{st.name}: its own renderer, not a layer behind words")
            continue
        params = lyric.default_params()
        clamped = P.backdrop_from(params, st.params)
        for line in clamped:
            print(f"    {st.name}: {line}")
        # Parked where the WORDS are, not where the drums are. This used to
        # nudge `cueing.offset` to the drum window instead -- which cannot
        # work: the offset is bounded to +-5s and the busiest drum window is a
        # minute into the song, so the words never arrived and the capture is
        # refused as wordless. A backdrop preview must show words with a beat
        # behind them, and words are the half that cannot be moved.
        P.reconcile(params)
        if params.validate():
            print(f"{st.name}: not valid behind words: {params.validate()}")
            failed.append(st.name)
            continue

        # The draft's "type" is the PATH it is filed under, and the path is
        # keyed by both renderers: which lyric renderer carries it, and which
        # beat renderer it is a look from. On the beat slug alone, two styles
        # sharing a name collapse into one video and the second is never even
        # recorded, because the first already made the file.
        # `type` is the renderer this draft IS -- lyric_grid, whose params
        # these are and whose field script builds it. `filed_under` is where
        # it is STORED, keyed by both renderers: on the beat slug alone, two
        # styles sharing a name collapse into one video and the second is never
        # recorded, because the first already made the file. Folding the path
        # into `type` instead made every capture raise `no video type
        # 'lyric_grid/pulse_grid'`, which is why these seven previews are the
        # ones the gallery was still showing from before the change.
        draft = S.Style(name=f"{st.name} behind", slug=st.slug,
                        type=lyric.slug,
                        filed_under=f"{lyric.slug}/{st.type}",
                        description=f"{st.description} — behind the words",
                        params=params)
        # Current, not merely present -- the same rule the styles use. Asking
        # only whether the file exists is how seven backdrop previews recorded
        # before the capture could read its params stayed in the gallery.
        if not force and draft.preview_is_current(BACKDROP_ROOT):
            print(f"{st.name} behind: preview already matches this look")
            continue
        for at in moments:
            print(f"{st.name} behind: recording from {at:.1f}s")
            try:
                S.capture_preview(client, draft, at=at, seconds=4.0,
                                  root=BACKDROP_ROOT, live=live,
                                  progress=lambda m: print("   ", m))
                break
            except S.StillPreview as e:
                print(f"    {e}")
            except S.FallbackPreview as e:
                # Not worth another moment: the picture would be the same
                # defaults at every one of them. Recorded as a failure here
                # rather than left to the for-else, which this break skips.
                print(f"    {e}")
                failed.append(st.name)
                break
        else:
            failed.append(st.name)
    return failed


def main(argv: list[str]) -> int:
    want_preview = "--preview" in argv
    # Re-record even a preview whose fingerprint matches. Needed whenever what
    # changed is the *capture* rather than the look: the fingerprint is of the
    # parameters, so a preview drawn from the wrong ones fingerprints as
    # current and nothing re-records it.
    force = "--force" in argv
    root = styles_mod.DEFAULT_ROOT
    made = build_styles()
    for st in made:
        path = st.save(root)
        print(f"wrote {path.relative_to(Path(__file__).resolve().parents[1])}")

    if not want_preview:
        return 0

    from lyricfield.config import Config
    from lyricfield.td_client import TDClient
    from lyricfield.workspace import Workspace

    client = TDClient()
    # Wrapped in a function: a bare `print(project.folder)` came back empty
    # here, which made the script go looking for a song called "" and fail in
    # ffmpeg rather than saying TouchDesigner had a different project open.
    slug = Path(client.run(
        "def go():\n    print(project.folder)\ngo()").strip()).name
    if not slug:
        print("TouchDesigner has no song project open; open one and retry")
        return 1
    try:
        live = Config.load(Workspace.open(slug).config_path)
    except FileNotFoundError:
        print(f"TouchDesigner has {slug!r} open, which is not a song workspace")
        return 1
    source = live.track.instrumental or live.track.source
    if not source or not Path(source).exists():
        print(f"{slug} has no readable source audio; previews need one")
        return 1
    print(f"previewing against {slug} ({live.track.duration:.0f}s, "
          f"beat {live.track.beat_period:.2f}s)")

    # Where the drums actually are, measured off the source. A fixed fraction
    # of the duration landed on a stretch of one song with no low-band events at
    # all, and five beatsync previews came back as still frames.
    from lyricfield import analysis
    spread = [m for m in (live.track.duration * f for f in (0.55, 0.3, 0.7))
              if 1.0 < m < live.track.duration - 8.0]
    beat_moments = [analysis.busiest_window(source, seconds=4.0)] + spread

    # A lyric style is parked where the WORDS are, not where the drums are.
    # The words a lyric preview shows are `styles.PREVIEW_CUES`, which spans
    # 0.4s to 7.5s and nothing else -- so parking at the busiest drum window,
    # often a minute in, records a field with no lyrics in it. Four of the five
    # lyric previews peaked at luma 68-123 of 255: the dim layer only, never one
    # bold cell. `cueing.offset` cannot rescue it either, being bounded to +-5s.
    # So slide the window over the table that is actually pushed, which is the
    # same rule `busiest_window` uses over the drums.
    from lyricfield.cues import CueTable
    from lyricfield.run import preview_window
    words = CueTable.load(styles_mod.PREVIEW_CUES).cues
    word_moments = [preview_window(live, words, 4.0)]
    last = max(c.start for c in words) if words else 0.0
    word_moments += [m for m in spread if m < last - 1.0]
    print(f"previewing beats from {beat_moments[0]:.1f}s, "
          f"words from {word_moments[0]:.1f}s "
          f"({len(words)} placeholder cues to {last:.1f}s)")

    def moments_for(family):
        return word_moments if family == types_mod.LYRIC else beat_moments

    failed = []
    for st in made:
        # Current, not merely present. Skipping on existence meant a look
        # could be re-tuned and keep the video of the look it used to be.
        if not force and st.preview_is_current(root):
            print(f"{st.name}: preview already matches this look")
            continue
        for at in moments_for(types_mod.get_type(st.type).family):
            print(f"{st.name}: recording from {at:.1f}s")
            try:
                styles_mod.capture_preview(
                    client, st, at=at, seconds=4.0, root=root, live=live,
                    progress=lambda m: print("   ", m))
                break
            except styles_mod.StillPreview as e:
                print(f"    {e}")
            except styles_mod.FallbackPreview as e:
                print(f"    {e}")
                failed.append(st.name)
                break
        else:
            failed.append(st.name)
    failed += backdrop_previews(client, live, root, word_moments, force=force)
    failed += builtin_previews(client, live, moments_for, force=force,
                           root=root)
    if failed:
        print(f"no moving preview for: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
