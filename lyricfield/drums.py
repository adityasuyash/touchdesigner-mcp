"""When each drum is struck, as a table the renderer can look up.

The beat response used to come from two RMS *level* gates inside TouchDesigner,
evaluated per frame. That could never work: a level threshold on a band holding
a sustained bassline crosses on bass notes and stays crossed while they sustain,
so the events had no relation to the drums -- measured over 44.8 seconds of
playback, the phase of their rising edges within the beat had a circular
concentration of 0.12, which is uniform.

Detecting onsets offline and pushing them in fixes that, and three other things
besides: the events are true onsets rather than level crossings, they are
identical in a preview and in a render because nothing depends on how fast
TouchDesigner happens to be cooking, and each one fires exactly once, so the
beat-cell throttle the beatsync types used to need -- which dropped 17% of the
kicks it was given -- can go.

Deliberately the same shape as `cues.py`: a TSV beside `cues.tsv`, a tab
separated body for a Table DAT, and a `from_dat_text` to read it back. That is
not tidiness, it is so `sync` and the field scripts need no new machinery.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass, field
from pathlib import Path

KICK, SNARE, HAT = "kick", "snare", "hat"
KINDS = (KICK, SNARE, HAT)


@dataclass(frozen=True)
class Hit:
    kind: str
    start: float


@dataclass
class DrumTable:
    hits: list[Hit] = field(default_factory=list)

    # ---------- construction ----------

    @classmethod
    def from_detection(cls, found: dict[str, list[float]]) -> "DrumTable":
        """From `analysis.detect_drums`'s output."""
        hits = [Hit(kind, round(float(t), 3))
                for kind in KINDS for t in found.get(kind, ())]
        return cls(sorted(hits, key=lambda h: (h.start, h.kind)))

    def times(self, kind: str) -> list[float]:
        return [h.start for h in self.hits if h.kind == kind]

    def __len__(self) -> int:
        return len(self.hits)

    def counts(self) -> dict[str, int]:
        return {k: sum(1 for h in self.hits if h.kind == k) for k in KINDS}

    # ---------- the DAT ----------

    def to_dat_text(self) -> str:
        rows = ["\t".join(["kind", "start_seconds"])]
        for h in sorted(self.hits, key=lambda h: (h.start, h.kind)):
            rows.append(f"{h.kind}\t{h.start:.3f}")
        return "\n".join(rows)

    @classmethod
    def from_dat_text(cls, text: str) -> "DrumTable":
        out, first = [], True
        for raw in text.splitlines():
            parts = raw.rstrip("\r").split("\t")
            if len(parts) < 2:
                continue
            kind = parts[0].strip()
            if first and kind.lower() == "kind":
                first = False
                continue
            first = False
            if kind not in KINDS:
                continue
            try:
                out.append(Hit(kind, float(parts[1])))
            except ValueError:
                continue
        return cls(sorted(out, key=lambda h: (h.start, h.kind)))

    # ---------- disk ----------

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_dat_text() + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> "DrumTable":
        path = Path(path)
        if not path.exists():
            return cls()
        return cls.from_dat_text(path.read_text(encoding="utf-8"))

    # ---------- problems ----------

    def problems(self, duration: float = 0.0) -> list[str]:
        out: list[str] = []
        if not self.hits:
            out.append("no drum hits were detected at all")
            return out
        if any(h.start < 0 for h in self.hits):
            out.append("a drum hit is before the start of the track")
        if duration and any(h.start > duration + 0.5 for h in self.hits):
            out.append("a drum hit is past the end of the track")
        return out


def fired(times: list[float], t: float, since: float) -> bool:
    """Did anything in `times` land in (since, t]?

    The lookup the field script does every frame, in place of evaluating a CHOP.
    Half-open so a hit is reported exactly once however the frame rate moves,
    which is what lets the beat-cell throttle go.
    """
    if not times or t <= since:
        return False
    i = bisect_left(times, since)
    return i < len(times) and times[i] > since and times[i] <= t
