"""Track preparation, end to end.

Given nothing but an audio file, produce everything the renderer needs:

    track.mp3
      -> separate    vocals.wav + no_vocals.wav          (Demucs)
      -> analyse     silences, kick entry, tempo, phase  (instrumental)
      -> transcribe  per-word cue table                  (Groq, vocal stem)
      -> config      paths and measured track facts persisted

Each stage is skipped when its output already exists, so a failed or interrupted
run resumes rather than repeating the slow parts. Separation takes minutes and
transcription costs money; neither should run twice by accident.

Order matters. Transcription reads the *vocal* stem, because isolated vocals give
markedly better word boundaries than a full mix. Analysis reads the *instrumental*,
because the voice otherwise pollutes onset detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import analysis as analysis_mod
from . import separate as separate_mod
from . import transcribe as transcribe_mod
from .config import Config
from .cues import CueTable
from .bands import BandTable
from .drums import DrumTable

# How far a first cue may trail the first singing before it counts as a lost
# opening line. Generous enough for a held breath or an ad-lib the transcriber
# reasonably skipped; august's gap was 5.9s.
LATE_CUE_GAP = 2.5


@dataclass
class Prepared:
    track: str = ""
    vocals: str = ""
    instrumental: str = ""
    duration: float = 0.0
    cues: int = 0
    lines: int = 0
    drums: int = 0
    drums_stem: str = ""
    bands: int = 0
    vocal_in: float = 0.0
    skipped: list[str] = field(default_factory=list)
    # Two kinds of bad news, deliberately separated. `problems` means the
    # machinery is wrong and the render cannot be trusted. `warnings` means the
    # *material* is imperfect -- a transcription that missed a line, words at an
    # identical timestamp -- which the user should see and can fix, but which
    # says nothing about whether the render itself came out right.
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    analysis: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "track": self.track,
            "vocals": self.vocals,
            "instrumental": self.instrumental,
            "duration": self.duration,
            "cues": self.cues,
            "lines": self.lines,
            "vocal_in": self.vocal_in,
            "skipped": self.skipped,
            "problems": self.problems,
            "warnings": self.warnings,
            "analysis": self.analysis,
        }


def prepare(track: str | Path,
            config_path: str | Path,
            cues_path: str | Path,
            drums_path: str | Path | None = None,
            bands_path: str | Path | None = None,
            stem_root: str | Path = separate_mod.DEFAULT_ROOT,
            model: str = separate_mod.DEFAULT_MODEL,
            device: str | None = None,
            groq_key: str | None = None,
            groq_model: str = transcribe_mod.DEFAULT_MODEL,
            language: str | None = None,
            prompt: str | None = None,
            force_separate: bool = False,
            force_analyse: bool = False,
            force_transcribe: bool = False,
            needs: frozenset | set | None = None,
            should_stop=None,
            progress=None) -> Prepared:
    """Produce only what the video type asked for.

    `needs` comes from `VideoType.needs`. A beatsync type on an instrumental
    track asks for the mix alone, so neither Demucs nor Groq is ever started --
    minutes and money not spent on stems and words nothing will read.
    """
    from .types import CUES, DRUMS, INSTRUMENTAL, VOCALS

    track = Path(track).expanduser()
    say = progress or (lambda m: None)
    out = Prepared(track=track.stem)
    needs = set(needs) if needs is not None else {INSTRUMENTAL, CUES}

    # ---- 1. stems ----
    stems = None
    if needs & {INSTRUMENTAL, VOCALS, DRUMS}:
        say("separating stems")
        stems = separate_mod.separate(
            track, root=stem_root, model=model, device=device,
            force=force_separate, progress=say, should_stop=should_stop)
        if stems.exists and not force_separate:
            out.skipped.append("separation (stems already present)")
        out.vocals = str(stems.vocals)
        out.instrumental = str(stems.instrumental)
        out.drums_stem = str(stems.rhythm or "")
    else:
        say("this video type needs no stems; skipping separation")
        out.skipped.append("separation (not needed by this video type)")

    # ---- 2. analysis ----
    # Skippable like separation and transcription: re-decoding the instrumental
    # and re-running the phase-lock sweep on every resume contradicted this
    # module's own promise that a stage whose output exists is not repeated.
    cfg = Config.load(config_path)
    # Analyse the instrumental when one exists, the source mix otherwise. Vocals
    # The song for the song-wide facts, the drums stem for the rhythm. NOT the
    # instrumental for either: it still carries the bassline, and measured
    # against the raw mix it detects fewer kicks and locks to the beat less
    # well (0.287 against 0.342; the drums stem gets 0.378).
    analysis_src = track
    rhythm_src = (stems.rhythm if stems else None) or track

    # Reusing an analysis is right when it was measured from the same audio AND
    # actually produced the drum table the renderer reads. Without that second
    # half a song analysed before drum detection existed keeps its cached
    # facts forever, writes an empty table, and renders with no beat response
    # at all -- a silent downgrade, which is the thing this pipeline keeps
    # having to be taught not to do.
    have_drums = bool(drums_path) and Path(drums_path).exists() \
        and len(DrumTable.load(drums_path)) > 0
    measured = (cfg.track.duration and cfg.track.beat_period and have_drums
                and cfg.track.drums == str(stems.rhythm or "" if stems else ""))
    if measured and not force_analyse:
        say(f"keeping existing analysis ({cfg.track.duration:.1f}s, "
            f"kick {cfg.track.kick_in:.1f}s)")
        out.skipped.append("analysis (already measured)")
        res = analysis_mod.Analysis(
            duration=cfg.track.duration, kick_in=cfg.track.kick_in,
            high_in=cfg.track.high_in, beat_period=cfg.track.beat_period,
            beat_anchor=cfg.track.beat_anchor, level=cfg.track.level,
            hold_windows=[tuple(w) for w in cfg.track.hold_windows])
    else:
        # Say which input, always. A silent downgrade to the mix is exactly
        # the kind of thing this project keeps having to go back and find.
        say(f"analysing the mix; beat from "
            f"{'the drums stem' if (stems and stems.rhythm) else 'the mix'}")
        res = analysis_mod.analyse(analysis_src, rhythm=rhythm_src)
    out.duration = res.duration
    out.analysis = res.to_dict()

    cfg.track.vocals = out.vocals
    cfg.track.instrumental = out.instrumental or str(analysis_src)
    cfg.track.drums = out.drums_stem
    cfg.track.duration = res.duration
    cfg.track.kick_in = res.kick_in
    cfg.track.high_in = res.high_in
    cfg.track.level = res.level
    cfg.track.beat_period = res.beat_period
    cfg.track.beat_anchor = res.beat_anchor
    cfg.track.hold_windows = [list(w) for w in res.hold_windows]

    # Where the singing starts. This is a fact about the vocal stem and nothing
    # else, so it is measured here rather than inside the cue-gap check further
    # down -- which ran *after* `cfg.save` and inside `if table.cues`, so the
    # value never reached the config and a song with no words never got one at
    # all. "Start before the vocals" reads exactly this number.
    if out.vocals:
        try:
            out.vocal_in = analysis_mod.vocal_entry(out.vocals)
        except Exception:      # a measurement, never a reason to fail the run
            out.vocal_in = 0.0
    if out.vocal_in:
        cfg.track.vocal_in = out.vocal_in

    # The drum hits go to a sidecar, not into the config: a busy track has
    # hundreds, and they do not belong in a TOML the UI rewrites on every edit.
    # Kept beside cues.tsv and pushed the same way.
    if drums_path is not None:
        drums = res.drum_table()
        if not len(drums) and Path(drums_path).exists():
            drums = DrumTable.load(drums_path)   # a reused analysis has none
            say(f"keeping existing drum table ({len(drums)} hits)")
        else:
            drums.save(drums_path)
            c = drums.counts()
            say(f"{c['kick']} kicks, {c['snare']} snares, {c['hat']} hats")
        out.drums = len(drums)
        # `DrumTable.problems()` opens with "no drum hits were detected at all"
        # and was called from nowhere in the package. Every renderer answers the
        # drums, so a table with none is a video that never moves -- and it was
        # announced as "0 kicks, 0 snares, 0 hats" and counted as a success.
        for msg in drums.problems(res.duration):
            out.warnings.append(msg)
            say(msg)

    # ---- 2b. the spectrum ----
    # Beside the drum table and written the same way. The drums say *when*
    # something is struck; this says where the energy is, which is the only
    # thing a bar renderer can be a picture of.
    if bands_path is not None:
        bands_path = Path(bands_path)
        # Named apart from `table`, which section 3 below uses for the cues.
        spectrum = BandTable.load(bands_path)
        if len(spectrum) and not force_analyse:
            say(f"keeping existing band table ({len(spectrum)} slices)")
        else:
            rhythm = cfg.track.instrumental or cfg.track.source
            try:
                levels = analysis_mod.detect_bands(
                    analysis_mod.decode_mono(rhythm))
                spectrum = BandTable.from_levels(levels)
                spectrum.save(bands_path)
                say(f"measured {len(spectrum)} band slices across "
                    f"{spectrum.bands} bands")
            except Exception as e:
                # A missing spectrum costs one renderer its picture; it must not
                # cost the whole ingest.
                out.warnings.append(f"could not measure the spectrum: {e}")
                say(f"could not measure the spectrum: {e}")
        out.bands = len(spectrum)
        for msg in spectrum.problems(res.duration):
            out.warnings.append(msg)
            say(msg)

    # ---- 3. cues ----
    cues_path = Path(cues_path)
    existing = CueTable.load(cues_path)
    if CUES not in needs:
        say("this video type needs no lyrics; skipping transcription")
        out.skipped.append("transcription (not needed by this video type)")
        table = existing
    elif existing.cues and not force_transcribe:
        say(f"keeping existing cue table ({len(existing.cues)} words)")
        out.skipped.append("transcription (cue table already present)")
        table = existing
    else:
        say("transcribing vocal stem with Groq")
        if stems is None:
            raise ValueError(
                "this video type asks for cues but not for stems; transcription "
                "needs an isolated vocal")
        table = transcribe_mod.transcribe_to_cues(
            stems.vocals, key=groq_key, model=groq_model,
            language=language, prompt=prompt)
        table.save(cues_path)
        say(f"{len(table.cues)} words across {len(table.lines)} lines")

    out.cues = len(table.cues)
    out.lines = len(table.lines)

    cfg.save(config_path)
    # Cue problems only matter to a type that draws cues. A beatsync renderer
    # legitimately has no words, and reporting "cue table is empty" for one is
    # a false alarm that withholds the verified marker from a perfectly good
    # render.
    out.problems = list(cfg.validate())
    if CUES in needs:
        out.warnings.extend(table.problems(res.duration))

    # Did transcription drop any lines? Compare the cue table against the stem
    # itself: sustained singing with no word cued against it means words were
    # lost, and nothing else in this data would have shown it.
    if table.cues and out.vocals:
        try:
            starts = [c.start for c in table.cues]
            gaps = analysis_mod.missed_windows(out.vocals, starts,
                                               min_voiced=LATE_CUE_GAP)
        except Exception:      # a measurement, never a reason to fail the run
            gaps = []
        for a, b, sung in gaps[:3]:
            where = "before the first cued word" if a == 0.0 else f"from {a:.1f}s"
            out.warnings.append(
                f"{sung:.1f}s of singing {where} (to {b:.1f}s) has no words "
                f"cued against it -- transcription probably dropped a line; "
                f"add the words to cues.tsv or re-run transcription")

    say("prepared")
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Prepare a track: separate, analyse, transcribe.")
    ap.add_argument("track")
    ap.add_argument("--config", default="data/config.toml")
    ap.add_argument("--cues", default="data/cues.tsv")
    ap.add_argument("--stem-root", default=str(separate_mod.DEFAULT_ROOT))
    ap.add_argument("--model", default=separate_mod.DEFAULT_MODEL)
    ap.add_argument("--device", default=None)
    ap.add_argument("--language", default=None)
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--force-separate", action="store_true")
    ap.add_argument("--force-analyse", action="store_true")
    ap.add_argument("--force-transcribe", action="store_true")
    a = ap.parse_args(argv)

    res = prepare(a.track, a.config, a.cues, stem_root=a.stem_root,
                  model=a.model, device=a.device, language=a.language,
                  prompt=a.prompt, force_separate=a.force_separate,
                  force_analyse=a.force_analyse,
                  force_transcribe=a.force_transcribe, progress=print)
    print()
    print(f"track        {res.track}")
    print(f"duration     {res.duration:.2f}s")
    print(f"vocals       {res.vocals}")
    print(f"instrumental {res.instrumental}")
    print(f"cues         {res.cues} words / {res.lines} lines")
    a_ = res.analysis
    print(f"kick in      {a_.get('kick_in')}s   tempo {a_.get('bpm')} BPM")
    print(f"silences     {a_.get('hold_windows')}")
    for p in res.problems:
        print(f"  warning: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
