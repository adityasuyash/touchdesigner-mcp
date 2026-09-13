"""The cue table: one row per word, with a start time and a line number.

This is the file the whole system revolves around. It is deliberately a plain TSV
so it diffs cleanly in git and can be hand-corrected in VSCode after Groq
transcription gets a word slightly wrong.

    word<TAB>start_seconds<TAB>line

Lyric text is user-supplied -- typed in the UI, imported from a file, or produced
by `lyricfield.transcribe`. Nothing is bundled with the source.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Cue:
    word: str
    start: float
    line: int


@dataclass
class CueTable:
    cues: list[Cue] = field(default_factory=list)

    # ---------- io ----------

    @classmethod
    def load(cls, path: str | Path) -> "CueTable":
        path = Path(path)
        if not path.exists():
            return cls()
        out: list[Cue] = []
        with path.open(newline="", encoding="utf-8") as fh:
            first = True
            for row in csv.reader(fh, delimiter="\t"):
                if not row or not row[0].strip():
                    continue
                head = row[0].strip()
                # Only the first row can be the header. Matching "word" anywhere
                # silently dropped that cue from any song that sings it.
                if head.startswith("#") or (first and head.lower() == "word"):
                    first = False
                    continue
                first = False
                try:
                    out.append(Cue(head, float(row[1]), int(float(row[2]))))
                except (IndexError, ValueError):
                    continue
        return cls(sorted(out, key=lambda c: c.start))

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, delimiter="\t", lineterminator="\n")
            w.writerow(["word", "start_seconds", "line"])
            for c in sorted(self.cues, key=lambda c: c.start):
                w.writerow([c.word, f"{c.start:.2f}", c.line])

    def to_dat_text(self) -> str:
        """Tab-separated body for the TD Table DAT, header included."""
        rows = ["\t".join(["word", "start_seconds", "line"])]
        for c in sorted(self.cues, key=lambda c: c.start):
            rows.append("\t".join([c.word, f"{c.start:.2f}", str(c.line)]))
        return "\n".join(rows)

    @classmethod
    def from_dat_text(cls, text: str) -> "CueTable":
        out: list[Cue] = []
        first = True
        for raw in text.splitlines():
            parts = raw.rstrip("\r").split("\t")
            if len(parts) < 3 or not parts[0].strip():
                continue
            if first and parts[0].strip().lower() == "word":
                first = False
                continue
            first = False
            try:
                out.append(Cue(parts[0].strip(), float(parts[1]), int(float(parts[2]))))
            except ValueError:
                continue
        return cls(sorted(out, key=lambda c: c.start))

    # ---------- shaping ----------

    @property
    def lines(self) -> dict[int, list[Cue]]:
        d: dict[int, list[Cue]] = {}
        for c in self.cues:
            d.setdefault(c.line, []).append(c)
        for k in d:
            d[k].sort(key=lambda c: c.start)
        return d

    def line_text(self, line: int) -> str:
        return " ".join(c.word for c in self.lines.get(line, []))

    def letters_per_line(self) -> dict[int, int]:
        return {ln: sum(len(c.word) for c in cs) for ln, cs in self.lines.items()}

    def shift(self, seconds: float) -> "CueTable":
        return CueTable([Cue(c.word, c.start + seconds, c.line) for c in self.cues])

    # ---------- validation ----------

    def problems(self, track_seconds: float | None = None) -> list[str]:
        """Everything that bit us during the TouchDesigner build, checked up front."""
        out: list[str] = []
        if not self.cues:
            return ["cue table is empty"]

        times = [c.start for c in self.cues]
        dupes = {t for t in times if times.count(t) > 1}
        if dupes:
            out.append(
                f"{len(dupes)} duplicate timestamp(s): {sorted(dupes)[:5]} — "
                "words at an identical time fire simultaneously"
            )
        if any(b < a for a, b in zip(times, times[1:])):
            out.append("cues are not sorted by time")
        if times[0] < 0:
            out.append(f"first cue is negative ({times[0]:.2f}s)")
        if track_seconds is not None and times[-1] > track_seconds:
            out.append(f"last cue {times[-1]:.2f}s is past the track ({track_seconds:.2f}s)")

        gaps = [b - a for a, b in zip(times, times[1:])]
        tight = sum(1 for g in gaps if g < 0.10)
        if tight:
            out.append(f"{tight} gap(s) under 0.10s — words will overlap heavily")

        seen: set[int] = set()
        last = None
        for c in self.cues:
            if c.line != last:
                if c.line in seen:
                    out.append(f"line {c.line} is not contiguous in time")
                seen.add(c.line)
                last = c.line

        longest = max(self.cues, key=lambda c: len(c.word))
        if len(longest.word) > 12:
            out.append(
                f"longest word is {len(longest.word)} chars — the grid is 24 wide and "
                "letters are spaced one cell apart, so anything over 12 wraps"
            )
        return out


_WORD = re.compile(r"[^\s]+")


def cues_from_lines(lines: list[str], starts: list[float], line_span: float = 3.0) -> CueTable:
    """Fallback when only per-LINE timings are known: distribute words evenly
    across each line's span. Groq word timestamps are far better; this exists so
    the UI still works when transcription is unavailable."""
    out: list[Cue] = []
    for i, (text, t0) in enumerate(zip(lines, starts)):
        words = _WORD.findall(text)
        if not words:
            continue
        end = starts[i + 1] if i + 1 < len(starts) else t0 + line_span
        step = (end - t0) * 0.55 / max(1, len(words))
        for j, w in enumerate(words):
            out.append(Cue(w, round(t0 + j * step, 2), i + 1))
    return CueTable(sorted(out, key=lambda c: c.start))
