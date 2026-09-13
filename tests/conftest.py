"""Shared fixtures.

Every media fixture is **synthesised by ffmpeg**, never a real song. That is not
only about licensing: a generated fixture has a ground truth a real recording
cannot give. A click train at exactly 120 BPM must measure 120; a black frame
must read 16.0 in limited-range luma; a video that flashes at known times must
correlate with those times and not with others. Assertions against a real track
can only ever say "about the same as last time".
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def pytest_collection_modifyitems(config, items):
    """Skip what the machine cannot run, rather than failing it."""
    skip_ffmpeg = pytest.mark.skip(reason="ffmpeg/ffprobe not on PATH")
    for item in items:
        if "ffmpeg" in item.keywords and not HAVE_FFMPEG:
            item.add_marker(skip_ffmpeg)


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                   check=True)


# --------------------------------------------------------------------- audio

@pytest.fixture(scope="session")
def media(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("media")


@pytest.fixture(scope="session")
def sine_wav(media: Path) -> Path:
    """2 seconds of 440Hz, mono."""
    out = media / "sine.wav"
    if not out.exists():
        _ff("-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-ac", "1", str(out))
    return out


@pytest.fixture(scope="session")
def stereo_wav(media: Path) -> Path:
    """10s stereo with a *different* tone per channel.

    The distinguishing tones are the point: `transcribe._compress` once used
    `adelay` with a single value, which moved only the first channel, and the
    downmix to mono then restored the original timing from the untouched second
    channel -- the shift vanished while the caller still corrected for it. A
    mono fixture cannot catch that.
    """
    out = media / "stereo.wav"
    if not out.exists():
        _ff("-f", "lavfi", "-i", "sine=frequency=300:duration=10",
            "-f", "lavfi", "-i", "sine=frequency=900:duration=10",
            "-filter_complex", "[0:a][1:a]amerge=inputs=2[a]", "-map", "[a]",
            "-ac", "2", str(out))
    return out


@pytest.fixture(scope="session")
def silence_then_tone(media: Path) -> Path:
    """3s of silence, then 3s of tone. Ground truth for onset detection."""
    out = media / "late_start.wav"
    if not out.exists():
        _ff("-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=3",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
            "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1[a]", "-map", "[a]",
            "-ac", "1", str(out))
    return out


@pytest.fixture(scope="session")
def click_train_120bpm(media: Path) -> Path:
    """Clicks at exactly 120 BPM (every 0.5s) over 16 seconds.

    Low-passed so the energy lands in the band `estimate_tempo` looks at.
    """
    out = media / "clicks120.wav"
    if not out.exists():
        _ff("-f", "lavfi",
            "-i", "sine=frequency=60:duration=16",
            "-af", "asetrate=44100,volume='if(lt(mod(t,0.5),0.05),1,0)':eval=frame",
            "-ac", "1", str(out))
    return out


# --------------------------------------------------------------------- video

@pytest.fixture(scope="session")
def black_mp4(media: Path) -> Path:
    out = media / "black.mp4"
    if not out.exists():
        _ff("-f", "lavfi", "-i", "color=black:size=64x64:rate=10:duration=6",
            "-pix_fmt", "yuv420p", str(out))
    return out


@pytest.fixture(scope="session")
def flashes_mp4(media: Path) -> Path:
    """Black for 10s, white between 1.0-2.0s and 5.0-6.0s.

    Those are the only bright moments, so a cue list naming them must score far
    better than one naming any other time. That asymmetry is the whole point of
    `picture_matches_cues`.
    """
    out = media / "flashes.mp4"
    if not out.exists():
        _ff("-f", "lavfi", "-i", "color=black:size=64x64:rate=10:duration=10",
            "-vf", "geq=lum='if(between(T,1,2)+between(T,5,6),255,0)':cb=128:cr=128",
            "-pix_fmt", "yuv420p", str(out))
    return out


@pytest.fixture(scope="session")
def half_and_half_png(media: Path) -> Path:
    """Top half black, bottom half white, 64x64.

    Pins the limited-range luma assumption that the whole verify stage rests on:
    black reads ~16, white ~235, and a crop must actually crop.
    """
    out = media / "half.png"
    if not out.exists():
        _ff("-f", "lavfi", "-i", "color=black:size=64x32",
            "-f", "lavfi", "-i", "color=white:size=64x32",
            "-filter_complex", "[0:v][1:v]vstack=inputs=2[v]", "-map", "[v]",
            "-frames:v", "1", str(out))
    return out


# --------------------------------------------------------------- repo objects

@pytest.fixture
def cfg():
    """A default config for the only shipped video type."""
    from lyricfield.config import Config
    return Config()


@pytest.fixture
def params():
    from lyricfield.types.lyric_grid.params import Params
    return Params()


@pytest.fixture
def field_mod():
    """`field.py` loaded as a module, fresh each time.

    It runs inside TouchDesigner but imports standalone: `_load_params` swallows
    the NameError from TD's `mod()` and falls back to DEFAULTS. A fresh copy per
    test matters because its tunables are module-level globals bound once at
    import, and `S` is module state.
    """
    import types as pytypes
    import numpy as np
    src = (REPO / "lyricfield" / "types" / "lyric_grid" / "field.py").read_text()
    mod = pytypes.ModuleType("field_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    return mod
