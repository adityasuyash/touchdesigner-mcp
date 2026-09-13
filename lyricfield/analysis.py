"""Audio structure detection for the instrumental stem.

The findings this produces drive the visual behaviour, and they are not cosmetic.
On the first track we built against, analysis revealed the "song" was actually
three spliced clips separated by true digital silence, with no kick at all for
the first 29.5 seconds. Every rhythm decision depended on knowing that, and none
of it was guessable by ear-less inspection of the waveform envelope alone.

What gets detected:
  * hold windows   -- stretches of digital silence (splice points). The field
                      freezes through these instead of going inert.
  * kick_in        -- when low-frequency percussion actually starts.
  * high_in        -- when the hi-hat / >4kHz layer enters, often the only
                      rhythmic reference available during an intro.
  * beat grid      -- tempo and phase, per segment. Phases of separate clips are
                      independent; never extrapolate one across a splice.

Requires numpy and ffmpeg on PATH.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from collections.abc import Sequence
from pathlib import Path

import numpy as np

SR = 22050


@dataclass
class Segment:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass
class Analysis:
    duration: float = 0.0
    hold_windows: list[tuple[float, float]] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)
    kick_in: float = 0.0
    high_in: float = 0.0
    beat_period: float = 0.4615
    beat_anchor: float = 0.0
    bpm: float = 130.0
    # How loud this master is: the 90th-percentile frame RMS. Every gate that
    # the TouchDesigner side applies as an absolute number has to be scaled by
    # this, or it means something different on every track.
    level: float = 0.0
    kick_times: list[float] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "duration": self.duration,
            "hold_windows": [list(w) for w in self.hold_windows],
            "segments": [[s.start, s.end] for s in self.segments],
            "kick_in": self.kick_in,
            "high_in": self.high_in,
            "level": self.level,
            "beat_period": self.beat_period,
            "beat_anchor": self.beat_anchor,
            "bpm": self.bpm,
            "kick_count": len(self.kick_times),
        }


class AudioUnreadable(RuntimeError):
    """A file that should hold audio could not be decoded.

    Raised rather than returning silence, because silence is indistinguishable
    from a real quiet passage: an empty decode yields duration 0, which sends
    the renderer to its fallback defaults and produces a plausible video of the
    wrong thing. A moved or renamed stem has to be loud.
    """


def _decode_error(path, proc) -> "AudioUnreadable":
    why = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
    hint = why[-1] if why else "ffmpeg gave no reason"
    if not Path(path).exists():
        hint = "the file does not exist"
    return AudioUnreadable(f"could not read audio from {path}: {hint}")


def probe_duration(path: str | Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
    )
    if out.returncode != 0:
        raise _decode_error(path, out)
    try:
        return float(out.stdout.decode().strip())
    except ValueError as e:
        raise _decode_error(path, out) from e


def decode_mono(path: str | Path, sr: int = SR) -> np.ndarray:
    """Decode to mono float32 at `sr` via ffmpeg. Avoids a soundfile dependency
    and handles every container ffmpeg does."""
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path),
         "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise _decode_error(path, proc)
    return np.frombuffer(proc.stdout, dtype=np.float32)


def _frame_rms(x: np.ndarray, fps: float, sr: int = SR) -> np.ndarray:
    hop = max(1, int(sr / fps))
    n = len(x) // hop
    if n == 0:
        return np.zeros(0, np.float32)
    return np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1)).astype(np.float32)


def _band_rms(x: np.ndarray, lo: float, hi: float, fps: float, sr: int = SR) -> np.ndarray:
    hop = max(1, int(sr / fps))
    n = len(x) // hop
    if n == 0:
        return np.zeros(0, np.float32)
    frames = x[: n * hop].reshape(n, hop)
    win = np.hanning(hop).astype(np.float32)
    spec = np.abs(np.fft.rfft(frames * win, axis=1))
    freqs = np.fft.rfftfreq(hop, 1.0 / sr)
    sel = (freqs >= lo) & (freqs <= hi)
    if not sel.any():
        return np.zeros(n, np.float32)
    return np.sqrt((spec[:, sel] ** 2).sum(axis=1) / sel.sum()).astype(np.float32)


def find_hold_windows(x: np.ndarray, fps: float = 50.0,
                      floor: float = 2e-4, min_len: float = 0.6,
                      sr: int = SR) -> list[tuple[float, float]]:
    """Stretches of near-digital silence. These are splice points, and the visual
    should hold its breath through them rather than sit inert.

    `floor` is the absolute noise level below which audio counts as silence, and
    it is also read *relative to the track*. On its own an absolute floor was
    the least portable number in this module: a quietly mastered or very dynamic
    recording has whole passages under it, and the renderer freezes its drift
    and suppresses every ripple and spark through a "splice point" that is
    really just a quiet verse. The relative term keeps a loud master's true
    digital silence from being missed, while a quiet one is judged against
    itself.
    """
    env = _frame_rms(x, fps, sr)
    if len(env):
        typical = float(np.percentile(env, 50))
        floor = max(floor, typical * 0.02)
    quiet = env < floor
    out: list[tuple[float, float]] = []
    i = 0
    while i < len(quiet):
        if quiet[i]:
            j = i
            while j < len(quiet) and quiet[j]:
                j += 1
            if (j - i) / fps >= min_len:
                out.append((round(i / fps, 2), round(j / fps, 2)))
            i = j
        else:
            i += 1
    return out


def _first_sustained(env: np.ndarray, fps: float, thresh: float,
                     sustain: float = 0.5) -> float:
    need = max(1, int(sustain * fps))
    run = 0
    for i, v in enumerate(env):
        run = run + 1 if v > thresh else 0
        if run >= need:
            return round((i - need + 1) / fps, 2)
    return 0.0


def _smooth(env: np.ndarray, fps: float, win: float = 1.0) -> np.ndarray:
    n = max(1, int(win * fps))
    return np.convolve(env, np.ones(n) / n, mode="same")


def high_entry(env: np.ndarray, fps: float = 50.0, thresh: float = 0.15) -> float:
    """When the >4kHz layer enters, measured against a typical level, not a peak.

    Normalising by the maximum is right for the kick, which dominates its own
    band wherever it plays, and wrong for hi-hats: one loud passage sets the
    peak and everything before it reads as silence. It put the hat entry of a
    264s song at 218s, and of a 91s song at 0s -- both badly wrong, in opposite
    directions. The 75th percentile is a robust stand-in for "a normal loud
    moment" and is not moved by a single drop.

    The envelope is smoothed first because hats are transient: two-second
    averages were well over the threshold from the moment they entered, while
    individual frames dipped under it constantly, so an unsmoothed sustain test
    waited 23 seconds for a run of frames that all happened to clear the bar.
    """
    if not len(env):
        return 0.0
    ref = float(np.percentile(env, 75))
    return _first_sustained(_smooth(env, fps) / (ref + 1e-9), fps,
                            thresh=thresh, sustain=0.5)


def voiced_frames(vocals: str | Path, fps: float = 50.0,
                  thresh: float = 0.06) -> tuple[np.ndarray, float]:
    """A per-frame "is someone singing here" mask for a vocal stem.

    The threshold is relative to the stem's own peak and deliberately low: a
    breathy verse is quiet next to the chorus that sets the peak, and every
    caller here only ever produces a warning.
    """
    x = decode_mono(vocals)
    if not len(x):
        return np.zeros(0, dtype=bool), fps
    env = _band_rms(x, 200.0, 4000.0, fps)
    if not len(env):
        return np.zeros(0, dtype=bool), fps
    return (env / (env.max() + 1e-9)) > thresh, fps


def missed_windows(vocals: str | Path, starts: Sequence[float],
                   min_voiced: float = 2.5,
                   fps: float = 50.0) -> list[tuple[float, float, float]]:
    """Stretches where the stem is singing but no word is cued.

    Transcription can drop lines without ever failing -- on one song it lost the
    whole opening couplet and hung the next line's words on its timestamps, so
    the cue count, the coverage and the end time all looked healthy. Nothing in
    the returned data said anything was wrong.

    The vocal stem is the ground truth and it is already on disk. Cues mark where
    words are; the stem marks where singing is. Sustained singing with no word
    against it is the signature of a dropped line, whether it was trimmed off the
    front or lost in the middle.

    Returns `(start, end, voiced_seconds)` per suspect gap, worst first.
    """
    voiced, fps = voiced_frames(vocals, fps)
    if not len(voiced):
        return []
    dur = len(voiced) / fps
    edges = [0.0, *sorted(starts), dur]
    out: list[tuple[float, float, float]] = []
    for a, b in zip(edges, edges[1:]):
        if b - a < min_voiced:
            continue
        span = voiced[int(a * fps):int(b * fps)]
        sung = float(span.sum()) / fps
        if sung >= min_voiced:
            out.append((round(a, 2), round(b, 2), round(sung, 2)))
    out.sort(key=lambda w: w[2], reverse=True)
    return out


def vocal_entry(vocals: str | Path, sustain: float = 0.25) -> float:
    """The moment singing actually starts, in seconds.

    Transcription can silently lose a quiet opening line -- Whisper's voice
    detection trims it -- and the only way to notice was to listen. The vocal
    stem is already on disk, so measure it instead: the first sustained energy
    in the range a voice occupies. Compared against the first cue, this turns a
    missing first line into a warning the run raises itself.

    The threshold, in `voiced_frames`, is deliberately low. A breathy opening
    line is quiet relative to the chorus that sets the peak, and missing a real
    entry matters more here than an occasional false one -- this only ever
    produces a warning.
    """
    voiced, fps = voiced_frames(vocals)
    if not len(voiced):
        return 0.0
    need = max(1, int(sustain * fps))
    run = 0
    for i, v in enumerate(voiced):
        run = run + 1 if v else 0
        if run >= need:
            return round((i - need + 1) / fps, 2)
    return 0.0


def estimate_tempo(x: np.ndarray, lo: float = 20.0, hi: float = 150.0,
                   fps: float = 100.0, bpm_range: tuple[float, float] = (60.0, 200.0),
                   sr: int = SR) -> tuple[float, float]:
    """Autocorrelation of low-band onset flux. Returns (period_seconds, bpm)."""
    env = _band_rms(x, lo, hi, fps, sr)
    if len(env) < 8:
        return 0.4615, 130.0
    flux = np.diff(env)
    flux[flux < 0] = 0.0
    flux = flux - flux.mean()
    ac = np.correlate(flux, flux, mode="full")[len(flux) - 1:]
    if ac[0] <= 0:
        return 0.4615, 130.0
    ac = ac / ac[0]
    lo_lag = int(fps * 60.0 / bpm_range[1])
    hi_lag = int(fps * 60.0 / bpm_range[0])
    hi_lag = min(hi_lag, len(ac) - 1)
    if hi_lag <= lo_lag:
        return 0.4615, 130.0
    peak = int(np.argmax(ac[lo_lag:hi_lag])) + lo_lag
    period = peak / fps
    return round(period, 4), round(60.0 / period, 2)


def lock_phase(x: np.ndarray, period: float, search_from: float = 0.0,
               fps: float = 100.0, sr: int = SR) -> float:
    """Slide a grid at `period` and pick the offset carrying the most onset energy."""
    env = _band_rms(x, 20.0, 150.0, fps, sr)
    flux = np.diff(env)
    flux[flux < 0] = 0.0
    best_ph, best_e = search_from, -1.0
    steps = max(1, int(period * fps))
    for s in range(steps):
        ph = search_from + s / fps
        idx = (np.arange(ph, len(flux) / fps, period) * fps).astype(int)
        idx = idx[(idx >= 0) & (idx < len(flux))]
        if not len(idx):
            continue
        e = float(flux[idx].sum())
        if e > best_e:
            best_e, best_ph = e, ph
    return round(best_ph, 3)


def detect_kicks(x: np.ndarray, thresh_pct: float = 88.0, min_gap: float = 0.22,
                 fps: float = 100.0, sr: int = SR) -> list[float]:
    env = _band_rms(x, 20.0, 150.0, fps, sr)
    if not len(env):
        return []
    env = env / (env.max() + 1e-9)
    up = float(np.percentile(env, thresh_pct))
    down = up * 0.55
    gap = int(min_gap * fps)
    out, armed, last = [], True, -10**9
    for i, v in enumerate(env):
        if armed and v > up and (i - last) >= gap:
            out.append(round(i / fps, 3))
            last, armed = i, False
        elif not armed and v < down:
            armed = True
    return out


def busiest_window(source: str | Path, seconds: float = 4.0,
                   avoid: float = 1.0) -> float:
    """Where in this track to look if you want to see it answering the drums.

    A style preview is a few seconds long, and the moment it is taken from
    decides whether it shows the style at all. Taking it from a fixed fraction
    of the duration put five beatsync previews on a stretch of one song where
    the low band never crossed its gate: the renders came back as still frames,
    and a still frame of a beat renderer is indistinguishable from a beat
    renderer that does not work.

    So pick by measuring -- the window holding the most kicks, ties to the
    earliest, which is the same rule `preview_window` uses over the cue table
    for a lyric type.
    """
    x = decode_mono(source)
    dur = len(x) / SR
    if dur <= seconds:
        return 0.0
    kicks = detect_kicks(x)
    latest = max(0.0, dur - seconds - avoid)
    if not kicks:
        return min(latest, dur * 0.4)
    best, best_n = 0.0, -1
    for start in kicks:
        start = min(max(avoid, start - 0.25), latest)
        n = sum(1 for k in kicks if start <= k < start + seconds)
        if n > best_n:
            best, best_n = start, n
    return round(best, 3)


def analyse(instrumental: str | Path) -> Analysis:
    path = Path(instrumental)
    x = decode_mono(path)
    dur = len(x) / SR

    holds = find_hold_windows(x)
    # audio that stops before the file ends is its own hold window
    tail_env = _frame_rms(x, 50.0)
    if len(tail_env) and tail_env[-1] < 2e-4:
        pass  # already captured by find_hold_windows

    segments: list[Segment] = []
    cursor = 0.0
    for a, b in holds:
        if a - cursor > 0.5:
            segments.append(Segment(round(cursor, 2), a))
        cursor = b
    if dur - cursor > 0.5:
        segments.append(Segment(round(cursor, 2), round(dur, 2)))

    low = _band_rms(x, 20.0, 150.0, 50.0)
    high = _band_rms(x, 4000.0, SR / 2 - 1, 50.0)
    low_n = low / (low.max() + 1e-9)
    high_n = high / (high.max() + 1e-9)

    # The kick keeps its peak-relative test: measured on two tracks it put the
    # drum entry within a couple of seconds of where the envelope visibly steps
    # up, because a kick dominates the low band wherever it plays. Hats do not,
    # so they get their own detector.
    kick_in = _first_sustained(low_n, 50.0, thresh=0.22)
    high_in = high_entry(high, 50.0)

    full = _frame_rms(x, 50.0)
    level = float(np.percentile(full, 90)) if len(full) else 0.0

    period, bpm = estimate_tempo(x)
    anchor = lock_phase(x, period, search_from=max(0.0, kick_in - period))
    kicks = detect_kicks(x)

    return Analysis(
        duration=round(dur, 3),
        hold_windows=holds,
        segments=segments,
        kick_in=kick_in,
        high_in=high_in,
        beat_period=period,
        beat_anchor=anchor,
        bpm=bpm,
        level=level,
        kick_times=kicks,
    )


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Analyse an instrumental stem.")
    ap.add_argument("instrumental")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = analyse(a.instrumental)
    if a.json:
        print(json.dumps(res.to_dict(), indent=2))
    else:
        d = res.to_dict()
        print(f"duration   {d['duration']:.2f}s")
        print(f"kick in    {d['kick_in']:.2f}s")
        print(f"high in    {d['high_in']:.2f}s")
        print(f"tempo      {d['bpm']:.1f} BPM (period {d['beat_period']:.4f}s, "
              f"anchor {d['beat_anchor']:.3f}s)")
        print(f"kicks      {d['kick_count']}")
        print(f"segments   {d['segments']}")
        print(f"silences   {d['hold_windows']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
