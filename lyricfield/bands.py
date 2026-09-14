"""How loud each frequency band is, over time, as a table the renderer reads.

Spectrum bars are the most recognisable music visual there is, and until this
existed the system could not draw them: the only rhythm data pushed into
TouchDesigner is `drums.tsv`, which says *when* a kick or a snare lands and
nothing at all about the spread of energy across the spectrum.

Deliberately the same shape as `drums.py`, which is itself the same shape as
`cues.py`: a TSV beside them, a tab-separated body for a Table DAT, and a
`from_dat_text` to read it back. Not tidiness -- it means `sync`, `preflight`
and the field scripts need no new machinery to carry it.

Measured offline for the same reason the drums are. A spectrum taken live inside
TouchDesigner depends on how fast it happens to be cooking, so a preview and a
render of the same second would not agree; measured here, a frame is a pure
function of its own timestamp.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

# How many bands, and the range they cover. Twenty-four is enough to read as a
# spectrum rather than as a handful of blocks, and few enough that one row per
# frame stays a sensible size on disk.
BANDS = 24
LO_HZ = 40.0
HI_HZ = 12000.0

# Rows per second. The renderer interpolates between rows, so this does not have
# to match the frame rate -- and should not, because a row per frame at 60fps is
# four times the file for no visible difference.
FPS = 30.0


@dataclass(frozen=True)
class Slice:
    """One moment, and the level of every band at it, each 0..1."""

    start: float
    levels: tuple[float, ...]


@dataclass
class BandTable:
    slices: list[Slice] = field(default_factory=list)
    bands: int = BANDS

    # ---------- construction ----------

    @classmethod
    def from_levels(cls, levels, fps: float = FPS) -> "BandTable":
        """From an (frames, bands) array of normalised levels."""
        out = []
        n_bands = 0
        for i, row in enumerate(levels):
            vals = tuple(round(float(v), 4) for v in row)
            n_bands = len(vals)
            out.append(Slice(round(i / float(fps), 3), vals))
        return cls(out, n_bands or BANDS)

    def __len__(self) -> int:
        return len(self.slices)

    @property
    def duration(self) -> float:
        return self.slices[-1].start if self.slices else 0.0

    def at(self, t: float) -> tuple[float, ...]:
        """The levels at `t`, interpolated between the two nearest rows.

        Interpolated rather than nearest-neighbour because the table is coarser
        than the frame rate on purpose: stepping between rows makes the bars
        visibly stair-step at 30 rows a second against 60 frames.
        """
        if not self.slices:
            return tuple([0.0] * self.bands)
        i = bisect_right([s.start for s in self.slices], t) - 1
        if i < 0:
            return self.slices[0].levels
        if i >= len(self.slices) - 1:
            return self.slices[-1].levels
        a, b = self.slices[i], self.slices[i + 1]
        span = b.start - a.start
        f = 0.0 if span <= 0 else (t - a.start) / span
        return tuple(x + (y - x) * f for x, y in zip(a.levels, b.levels))

    # ---------- the DAT ----------

    def to_dat_text(self) -> str:
        head = ["start_seconds"] + [f"b{i}" for i in range(self.bands)]
        rows = ["\t".join(head)]
        for s in self.slices:
            rows.append("\t".join([f"{s.start:.3f}"]
                                  + [f"{v:.4f}" for v in s.levels]))
        return "\n".join(rows)

    @classmethod
    def from_dat_text(cls, text: str) -> "BandTable":
        out, bands, first = [], 0, True
        for raw in text.splitlines():
            parts = raw.rstrip("\r").split("\t")
            if len(parts) < 2:
                continue
            if first and parts[0].strip().lower().startswith("start"):
                first = False
                bands = len(parts) - 1
                continue
            first = False
            try:
                start = float(parts[0])
                levels = tuple(float(v) for v in parts[1:])
            except ValueError:
                continue
            bands = bands or len(levels)
            out.append(Slice(start, levels))
        return cls(sorted(out, key=lambda s: s.start), bands or BANDS)

    # ---------- disk ----------

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_dat_text() + "\n", encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: str | Path) -> "BandTable":
        path = Path(path)
        if not path.exists():
            return cls()
        return cls.from_dat_text(path.read_text(encoding="utf-8"))

    # ---------- problems ----------

    def problems(self, duration: float = 0.0) -> list[str]:
        out: list[str] = []
        if not self.slices:
            out.append("no band levels were measured at all")
            return out
        if any(len(s.levels) != self.bands for s in self.slices):
            out.append("some rows hold a different number of bands")
        if any(v < 0.0 or v > 1.0 for s in self.slices for v in s.levels):
            out.append("a band level is outside 0..1, so it was not normalised")
        if duration and self.duration < duration * 0.5:
            out.append(
                f"the band table covers {self.duration:.0f}s of a "
                f"{duration:.0f}s song, so most of it would render flat")
        # A table that never moves is the failure mode worth naming: it looks
        # exactly like a working one until you watch the bars.
        if len(self.slices) > 2:
            first = self.slices[0].levels
            if all(s.levels == first for s in self.slices):
                out.append("every row is identical; the spectrum never moves")
        return out
