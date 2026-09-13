"""Stem separation via Demucs.

Every track needs two things before anything else can happen: an isolated vocal
(so Whisper produces clean word timestamps) and an instrumental (so the beat
analysis is not confused by the voice). Demucs produces both in one pass with
`--two-stems=vocals`.

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

    @property
    def exists(self) -> bool:
        return self.vocals.exists() and self.instrumental.exists()

    def to_dict(self) -> dict:
        return {
            "track": self.track,
            "vocals": str(self.vocals),
            "instrumental": str(self.instrumental),
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
               model: str = DEFAULT_MODEL, stem: str = "vocals") -> StemSet:
    """Where Demucs will put the output: <root>/<model>/<track name>/<stem>.wav"""
    track = Path(track)
    root = Path(root).expanduser()
    folder = root / model / track.stem
    return StemSet(
        track=track.stem,
        vocals=folder / f"{stem}.wav",
        instrumental=folder / f"no_{stem}.wav",
        model=model,
        root=root,
    )


def separate(track: str | Path, root: str | Path = DEFAULT_ROOT,
             model: str = DEFAULT_MODEL, stem: str = "vocals",
             device: str | None = None, force: bool = False,
             jobs: int = 1, progress=None) -> StemSet:
    """Split `track` into <stem> and no_<stem>. Returns existing stems unless forced."""
    track = Path(track).expanduser()
    if not track.exists():
        raise SeparationError(f"no such file: {track}")

    out = stem_paths(track, root, model, stem)
    say = progress or (lambda m: None)

    if out.exists and not force:
        say(f"stems already present for {out.track}")
        return out

    out.root.mkdir(parents=True, exist_ok=True)
    dev = pick_device(device)
    cmd = [
        find_demucs(),
        "-n", model,
        "--two-stems", stem,
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
    if not out.exists:
        raise SeparationError(
            f"demucs finished but expected stems are missing at {out.vocals.parent}. "
            "Check the --two-stems name matches the model's sources."
        )
    say(f"stems ready: {out.vocals.parent}")
    return out


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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
