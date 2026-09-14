"""Stem separation via Demucs.

Every track needs an isolated vocal (so Whisper produces clean word timestamps),
an instrumental (so the render can mux the song back together), and -- the one
this project spent a long time not keeping -- an isolated **drums** stem, which
is what onset detection should be looking at.

This used to ask for `--two-stems=vocals`, and that was pure loss. Demucs runs
the full four-source model either way; `--two-stems` computes drums, bass and
other, sums them into `no_vocals`, and **discards them**. So the drums stem was
being produced on every separation this project has ever run, and thrown away.
Asking for all four costs no extra model time, only three more WAV writes.

`no_vocals` is not produced in four-stem mode, so it is summed back here -- the
same plain add demucs itself does.

Why it matters: `no_vocals` still contains the bassline, and a kick detector
looks at 20-150 Hz where a sustained bass note lives and lasts far longer than a
kick. Measured on one track, kick phase-lock within the beat was 0.287 from the
instrumental, 0.342 from the raw mix, and 0.378 from the drums stem.

Demucs is normally installed in its own environment — pipx, or a separate venv —
so this shells out to the CLI rather than importing it. That keeps torch out of
this project's dependency tree entirely.

Separation is slow (minutes per track, longer on CPU), so `separate()` returns
existing stems untouched unless `force=True`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MODEL = "htdemucs"
DEFAULT_ROOT = Path.home() / "separated"

# pipx installs land here and are often not on a non-interactive PATH
_FALLBACKS = [
    Path.home() / ".local" / "bin" / "demucs",
    Path("/opt/homebrew/bin/demucs"),
    Path("/usr/local/bin/demucs"),
]


class SeparationError(RuntimeError):
    pass


@dataclass
class StemSet:
    track: str
    vocals: Path
    instrumental: Path
    model: str
    root: Path
    drums: Path | None = None
    bass: Path | None = None
    other: Path | None = None

    @property
    def exists(self) -> bool:
        """Every stem this set claims, not just the two it used to.

        If this only checked vocals and no_vocals, every song separated before
        four-stem mode would report itself complete and then hand out a drums
        path pointing at nothing -- and nothing downstream asserts a stem file
        exists, so the failure would surface much later as a decode error, or
        not at all.
        """
        need = [self.vocals, self.instrumental]
        need += [p for p in (self.drums, self.bass, self.other) if p is not None]
        return all(p.exists() for p in need)

    @property
    def rhythm(self) -> Path:
        """What a drum detector should listen to.

        The drums stem when there is one; otherwise nothing from this set --
        the caller falls back to the mix, which measures better than the
        instrumental does.
        """
        return self.drums if (self.drums and self.drums.exists()) else None

    def to_dict(self) -> dict:
        return {
            "track": self.track,
            "vocals": str(self.vocals),
            "instrumental": str(self.instrumental),
            "drums": str(self.drums) if self.drums else "",
            "model": self.model,
            "exists": self.exists,
        }


def find_demucs() -> str:
    exe = shutil.which("demucs")
    if exe:
        return exe
    for p in _FALLBACKS:
        if p.exists():
            return str(p)
    raise SeparationError(
        "demucs not found. Install it with `pipx install demucs` (recommended, "
        "keeps torch isolated) or `pip install demucs`, then retry."
    )


def pick_device(explicit: str | None = None) -> str:
    """Apple Silicon has an MPS backend that is dramatically faster than CPU.
    Demucs defaults to cpu when cuda is absent, so ask for mps explicitly."""
    if explicit:
        return explicit
    if os.uname().sysname == "Darwin" and os.uname().machine == "arm64":
        return "mps"
    return "cpu"


def stem_paths(track: str | Path, root: str | Path = DEFAULT_ROOT,
               model: str = DEFAULT_MODEL, stem: str = "vocals",
               all_stems: bool = True) -> StemSet:
    """Where Demucs will put the output: <root>/<model>/<track name>/<stem>.wav

    `all_stems=False` describes the old two-stem layout, which is what every
    song separated before this change has on disk. It is how an existing song
    is recognised as complete rather than re-separated.
    """
    track = Path(track)
    root = Path(root).expanduser()
    folder = root / model / track.stem
    return StemSet(
        track=track.stem,
        vocals=folder / f"{stem}.wav",
        instrumental=folder / f"no_{stem}.wav",
        drums=(folder / "drums.wav") if all_stems else None,
        bass=(folder / "bass.wav") if all_stems else None,
        other=(folder / "other.wav") if all_stems else None,
        model=model,
        root=root,
    )


def separate(track: str | Path, root: str | Path = DEFAULT_ROOT,
             model: str = DEFAULT_MODEL, stem: str = "vocals",
             device: str | None = None, force: bool = False,
             jobs: int = 1, progress=None, should_stop=None) -> StemSet:
    """Split `track` into all four stems. Returns existing stems unless forced."""
    track = Path(track).expanduser()
    if not track.exists():
        raise SeparationError(f"no such file: {track}")

    out = stem_paths(track, root, model, stem)
    say = progress or (lambda m: None)

    if out.exists and not force:
        say(f"stems already present for {out.track}")
        return out

    # A song separated before four-stem mode has vocals and no_vocals and
    # nothing else. Re-separating it is minutes of work for a stem the user did
    # not ask for, so it is left as it is and described honestly -- the caller
    # falls back to the mix for rhythm. "Separate again" upgrades it.
    old = stem_paths(track, root, model, stem, all_stems=False)
    if old.exists and not force:
        say(f"two-stem output already present for {old.track}; "
            "tick 'Separate again' to add a drums stem")
        return old

    out.root.mkdir(parents=True, exist_ok=True)
    dev = pick_device(device)
    # All four sources. `--two-stems` computed these and threw three away: the
    # model runs identically either way, so this costs three WAV writes and no
    # extra inference at all.
    cmd = [
        find_demucs(),
        "-n", model,
        "-d", dev,
        "-j", str(jobs),
        "-o", str(out.root),
        str(track),
    ]
    say(f"separating with {model} on {dev} — this takes a few minutes")

    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        # Separation is the longest thing the system does, so a stop has to be
        # able to end it rather than wait it out.
        if should_stop is not None and should_stop():
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise SeparationError("separation stopped")
        line = line.rstrip()
        if not line:
            continue
        tail.append(line)
        del tail[:-40]
        # demucs draws a progress bar on stderr; surface only meaningful lines
        if "%" in line or "Separat" in line or "error" in line.lower():
            say(line[:160])
    code = proc.wait()
    if code != 0:
        raise SeparationError(
            f"demucs exited {code}:\n" + "\n".join(tail[-15:])
        )
    made = [p for p in (out.vocals, out.drums, out.bass, out.other) if p]
    missing = [p.name for p in made if not p.exists()]
    if missing:
        raise SeparationError(
            f"demucs finished but {', '.join(missing)} are missing at "
            f"{out.vocals.parent}. Check the model's source names."
        )
    _sum_instrumental(out, say)
    say(f"stems ready: {out.vocals.parent}")
    return out


def _sum_instrumental(out: StemSet, say) -> None:
    """Rebuild `no_vocals` from the other three.

    Four-stem mode does not write one -- only `--two-stems` does, and it makes
    it by adding the rest together. This is the same plain add, not an average,
    which is why `normalize=0` is required: `amix` otherwise divides by the
    input count and the instrumental comes back a third of its proper level.
    """
    if out.instrumental.exists():
        return
    parts = [p for p in (out.drums, out.bass, out.other) if p and p.exists()]
    if len(parts) < 2:
        return
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for p in parts:
        cmd += ["-i", str(p)]
    cmd += ["-filter_complex",
            f"amix=inputs={len(parts)}:duration=longest:normalize=0",
            str(out.instrumental)]
    say("rebuilding the instrumental from the other stems")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise SeparationError(
            "could not rebuild the instrumental:\n" + proc.stderr[-500:])


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Separate a track into vocal + instrumental.")
    ap.add_argument("track")
    ap.add_argument("-o", "--out", default=str(DEFAULT_ROOT))
    ap.add_argument("-n", "--model", default=DEFAULT_MODEL)
    ap.add_argument("-d", "--device", default=None, help="mps, cuda, cpu")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    res = separate(a.track, root=a.out, model=a.model, device=a.device,
                   force=a.force, progress=print)
    print(f"vocals:       {res.vocals}")
    print(f"instrumental: {res.instrumental}")
    print(f"drums:        {res.drums or '(two-stem output, none)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
