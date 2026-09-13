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

# (type, name, description, {section.field: value})
LOOKS: list[tuple[str, str, str, dict]] = [
    # The lyric look. It has to be *distinct from the defaults*, or the gallery
    # shows two tiles for one look: when the built-in timing was tuned it was
    # tuned to match this file exactly, and the style quietly became a copy of
    # the thing it sits next to. Calm means calmer than the default, not equal
    # to it -- longer dissolve, slower drift, softer beat.
    ("lyric_grid", "Calm Drift",
     "longer dissolves, slower drift and a softer beat than the default",
     {"look.dissolve": 3.6, "look.drift_min": 4.5, "look.drift_max": 9.0,
      "cueing.hold": 1.25, "cueing.ramp_dn": 0.45, "cueing.letter_spread": 0.09,
      "beat.ripple_lift": 0.12, "beat.spark_peak": 0.45,
      "beat.spark_frac": 0.05, "beat.twinkle_lift": 0.14}),

    ("pulse_grid", "Sweep",
     "a crest crossing the field in time with the beat — the balanced one",
     {"look.dim_hue": 0.55, "pulse.wave_width": 4.5, "pulse.wave_lift": 0.38,
      "pulse.density": 0.68, "pulse.reroll": 14.0}),

    ("pulse_grid", "Cascade",
     "the same crest turned on its side and quickened, so it reads as falling",
     {"look.dim_hue": 0.62, "pulse.vertical": True, "pulse.wave_beats": 2.0,
      "pulse.wave_width": 1.8, "pulse.wave_lift": 0.40, "pulse.density": 0.80,
      "pulse.kick_lift": 0.18, "pulse.snare_frac": 0.05, "pulse.reroll": 8.0}),

    ("pulse_grid", "Heartbeat",
     "almost no sweep; the kick is the whole picture, wide and slow",
     {"look.dim_hue": 0.02, "look.dim_sat": 0.45, "pulse.wave_beats": 8.0,
      "pulse.wave_width": 6.0, "pulse.wave_lift": 0.06, "pulse.density": 0.60,
      "pulse.kick_lift": 0.45, "pulse.kick_time": 0.90, "pulse.kick_sigma": 4.5,
      "pulse.snare_peak": 0.35, "pulse.snare_frac": 0.03,
      "pulse.high_lift": 0.05}),

    ("pulse_grid", "Shimmer",
     "a dense field with no sweep at all; the hats and the snare carry it",
     {"look.dim_hue": 0.50, "look.dim_sat": 0.22, "pulse.wave_lift": 0.02,
      "pulse.density": 0.95, "pulse.high_lift": 0.35, "pulse.snare_frac": 0.14,
      "pulse.snare_peak": 0.56, "pulse.snare_time": 0.18,
      "pulse.kick_lift": 0.12, "pulse.lit_at": 0.50, "pulse.reroll": 5.0}),

    ("pulse_grid", "Constellation",
     "sparse, slow and wide — few points, held a long time",
     {"look.dim_hue": 0.68, "look.level_min": 0.08, "pulse.wave_beats": 12.0,
      "pulse.wave_width": 7.0, "pulse.wave_lift": 0.30, "pulse.density": 0.22,
      "pulse.glyphs": ".:*+", "pulse.kick_lift": 0.22, "pulse.kick_time": 0.90,
      "pulse.kick_sigma": 3.0, "pulse.snare_frac": 0.03,
      "pulse.high_lift": 0.10, "pulse.reroll": 45.0}),
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


def main(argv: list[str]) -> int:
    want_preview = "--preview" in argv
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
    slug = Path(client.run("print(project.folder)").strip()).name
    live = Config.load(Workspace.open(slug).config_path)
    print(f"previewing against {slug} ({live.track.duration:.0f}s, "
          f"beat {live.track.beat_period:.2f}s)")

    # Where the drums actually are, measured off the source. A fixed fraction
    # of the duration landed on a stretch of one song with no low-band events at
    # all, and five beatsync previews came back as still frames.
    from lyricfield import analysis
    source = live.track.instrumental or live.track.source
    moments = [analysis.busiest_window(source, seconds=4.0)]
    moments += [m for m in (live.track.duration * f for f in (0.55, 0.3, 0.7))
                if 1.0 < m < live.track.duration - 8.0]
    print(f"previewing from {moments[0]:.1f}s "
          f"(fallbacks {', '.join(f'{m:.0f}s' for m in moments[1:])})")

    failed = []
    for st in made:
        if st.preview_video(root).exists():
            print(f"{st.name}: preview already there")
            continue
        for at in moments:
            print(f"{st.name}: recording from {at:.1f}s")
            try:
                styles_mod.capture_preview(
                    client, st, at=at, seconds=4.0, root=root, live=live,
                    progress=lambda m: print("   ", m))
                break
            except styles_mod.StillPreview as e:
                print(f"    {e}")
        else:
            failed.append(st.name)
    if failed:
        print(f"no moving preview for: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
