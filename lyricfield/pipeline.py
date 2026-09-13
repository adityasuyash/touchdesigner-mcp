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


@dataclass
class Prepared:
    track: str = ""
    vocals: str = ""
    instrumental: str = ""
    duration: float = 0.0
    cues: int = 0
    lines: int = 0
    skipped: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    analysis: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "track": self.track,
            "vocals": self.vocals,
            "instrumental": self.instrumental,
            "duration": self.duration,
            "cues": self.cues,
            "lines": self.lines,
            "skipped": self.skipped,
            "problems": self.problems,
            "analysis": self.analysis,
        }


def prepare(track: str | Path,
            config_path: str | Path,
            cues_path: str | Path,
            stem_root: str | Path = separate_mod.DEFAULT_ROOT,
            model: str = separate_mod.DEFAULT_MODEL,
            device: str | None = None,
            groq_key: str | None = None,
            groq_model: str = transcribe_mod.DEFAULT_MODEL,
            language: str | None = None,
            prompt: str | None = None,
            force_separate: bool = False,
            force_transcribe: bool = False,
            progress=None) -> Prepared:
    track = Path(track).expanduser()
    say = progress or (lambda m: None)
    out = Prepared(track=track.stem)

    # ---- 1. stems ----
    say("separating stems")
    stems = separate_mod.separate(
        track, root=stem_root, model=model, device=device,
        force=force_separate, progress=say)
    if stems.exists and not force_separate:
        out.skipped.append("separation (stems already present)")
    out.vocals = str(stems.vocals)
    out.instrumental = str(stems.instrumental)

    # ---- 2. analysis ----
    say("analysing instrumental")
    res = analysis_mod.analyse(stems.instrumental)
    out.duration = res.duration
    out.analysis = res.to_dict()

    cfg = Config.load(config_path)
    cfg.track.vocals = out.vocals
    cfg.track.instrumental = out.instrumental
    cfg.track.duration = res.duration
    cfg.track.kick_in = res.kick_in
    cfg.track.high_in = res.high_in
    cfg.track.beat_period = res.beat_period
    cfg.track.beat_anchor = res.beat_anchor
    cfg.track.hold_windows = [list(w) for w in res.hold_windows]

    # the field script holds the grid for the whole timeline, which runs past the
    # last cue; without this the tail reverts to the baked-in fallback
    cfg.cueing.ambient_cycle = cfg.cueing.ambient_cycle or 6.0

    # ---- 3. cues ----
    cues_path = Path(cues_path)
    existing = CueTable.load(cues_path)
    if existing.cues and not force_transcribe:
        say(f"keeping existing cue table ({len(existing.cues)} words)")
        out.skipped.append("transcription (cue table already present)")
        table = existing
    else:
        say("transcribing vocal stem with Groq")
        table = transcribe_mod.transcribe_to_cues(
            stems.vocals, key=groq_key, model=groq_model,
            language=language, prompt=prompt)
        table.save(cues_path)
        say(f"{len(table.cues)} words across {len(table.lines)} lines")

    out.cues = len(table.cues)
    out.lines = len(table.lines)

    cfg.save(config_path)
    out.problems = table.problems(res.duration) + cfg.validate()
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
    ap.add_argument("--force-transcribe", action="store_true")
    a = ap.parse_args(argv)

    res = prepare(a.track, a.config, a.cues, stem_root=a.stem_root,
                  model=a.model, device=a.device, language=a.language,
                  prompt=a.prompt, force_separate=a.force_separate,
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
