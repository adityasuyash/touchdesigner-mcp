"""The measured spectrum, and the table that carries it.

Bars are the only picture in the system that is a *measurement* rather than a
reaction, so the thing worth testing is whether the measurement is true: energy
at a known frequency has to land in the band that covers that frequency, and not
in its neighbours. Everything else follows from that.

The fixtures are synthesised rather than recorded, for the reason CLAUDE.md
gives: a generated tone has a ground truth a real track cannot.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from lyricfield import analysis as A
from lyricfield.bands import BANDS, BandTable, Slice


def _tone(tmp_path: Path, hz: float, seconds: float = 3.0) -> Path:
    out = tmp_path / f"tone{int(hz)}.wav"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", f"sine=frequency={hz}:duration={seconds}",
         "-ar", "22050", "-ac", "1", str(out)], check=True)
    return out


def _edges(bands: int = 24, lo: float = 40.0, hi: float = 11025.0):
    return np.geomspace(lo, min(hi, A.SR / 2.0), bands + 1)


# ---------------------------------------------------------- the measurement

@pytest.mark.ffmpeg
@pytest.mark.parametrize("hz", [110.0, 440.0, 2000.0, 6000.0])
def test_a_tone_lands_in_the_band_that_covers_it(tmp_path, hz):
    """The whole point. A bar chart that puts a bass note in a treble bar is a
    picture of nothing, and it looks exactly like one that works."""
    x = A.decode_mono(_tone(tmp_path, hz))
    levels = A.detect_bands(x, bands=24, fps=30.0)
    loudest = int(np.argmax(levels.mean(axis=0)))
    edges = _edges(24)
    assert edges[loudest] <= hz <= edges[loudest + 1], (
        f"{hz} Hz landed in the band covering "
        f"{edges[loudest]:.0f}-{edges[loudest + 1]:.0f} Hz")


@pytest.mark.ffmpeg
def test_a_tone_does_not_light_the_whole_spectrum(tmp_path):
    x = A.decode_mono(_tone(tmp_path, 440.0))
    m = A.detect_bands(x, bands=24, fps=30.0).mean(axis=0)
    loudest = int(np.argmax(m))
    far = [v for i, v in enumerate(m) if abs(i - loudest) > 3]
    assert max(far) < m[loudest] * 0.9, (
        "a pure tone should not raise bands four away from it")


@pytest.mark.ffmpeg
def test_the_bands_are_spaced_by_pitch_rather_than_by_hertz(tmp_path):
    """Linear edges put eighteen of twenty-four bands above 4kHz, where almost
    no musical energy lives, and the chart is then twenty dead bars."""
    e = _edges(24)
    widths = np.diff(e)
    assert widths[-1] > widths[0] * 10


@pytest.mark.ffmpeg
def test_levels_are_normalised_into_range(tmp_path):
    x = A.decode_mono(_tone(tmp_path, 440.0))
    levels = A.detect_bands(x, bands=24, fps=30.0)
    assert levels.min() >= 0.0 and levels.max() <= 1.0


def test_silence_measures_flat_rather_than_raising_an_error():
    """`_band_rms` refuses a band with no FFT bin in it, which at any sensible
    frame rate is every low band. Bucketing one spectrogram avoids that, and
    silence has to come back as a valid, flat measurement."""
    levels = A.detect_bands(np.zeros(22050, np.float32), bands=24, fps=30.0)
    assert levels.shape[1] == 24
    assert float(levels.max()) == pytest.approx(0.0)


def test_no_audio_at_all_is_an_empty_measurement():
    assert A.detect_bands(np.zeros(0, np.float32)).shape[0] == 0


# ----------------------------------------------------------------- the table

def test_it_round_trips_through_the_dat_body():
    t = BandTable.from_levels([[0.1] * 4, [0.5] * 4, [0.9] * 4], fps=10.0)
    back = BandTable.from_dat_text(t.to_dat_text())
    assert len(back) == 3
    assert back.bands == 4
    assert back.slices[1].levels == pytest.approx(t.slices[1].levels)


def test_it_round_trips_through_disk(tmp_path):
    t = BandTable.from_levels([[0.25] * 6, [0.75] * 6], fps=10.0)
    p = t.save(tmp_path / "bands.tsv")
    assert BandTable.load(p).slices == t.slices


def test_a_missing_file_loads_as_empty(tmp_path):
    assert len(BandTable.load(tmp_path / "nope.tsv")) == 0


def test_levels_are_interpolated_between_slices():
    """The table is deliberately coarser than the frame rate. Stepping between
    rows makes every bar visibly stair-step at 30 rows against 60 frames."""
    t = BandTable([Slice(0.0, (0.0,)), Slice(1.0, (1.0,))], bands=1)
    assert t.at(0.5)[0] == pytest.approx(0.5)
    assert t.at(0.25)[0] == pytest.approx(0.25)


def test_before_the_first_and_after_the_last_hold_rather_than_extrapolate():
    t = BandTable([Slice(1.0, (0.3,)), Slice(2.0, (0.7,))], bands=1)
    assert t.at(0.0)[0] == pytest.approx(0.3)
    assert t.at(99.0)[0] == pytest.approx(0.7)


def test_an_empty_table_answers_with_silence():
    assert BandTable().at(3.0) == tuple([0.0] * BANDS)


# --------------------------------------------------------------- problems

def test_an_empty_table_says_so():
    assert "no band levels" in " ".join(BandTable().problems())


def test_a_table_that_never_moves_is_reported():
    """The failure worth naming: it looks exactly like a working table until
    somebody watches the bars."""
    t = BandTable.from_levels([[0.4] * 4] * 10, fps=10.0)
    assert any("never moves" in m for m in t.problems())


def test_a_table_covering_a_fraction_of_the_song_is_reported():
    t = BandTable.from_levels([[0.1] * 4, [0.9] * 4], fps=10.0)
    assert any("would render flat" in m for m in t.problems(duration=120.0))


def test_levels_outside_the_range_are_reported():
    t = BandTable([Slice(0.0, (1.5,)), Slice(0.1, (0.2,))], bands=1)
    assert any("not normalised" in m for m in t.problems())


def test_a_healthy_table_reports_nothing():
    levels = np.linspace(0.0, 1.0, 40).reshape(10, 4)
    t = BandTable.from_levels(levels, fps=10.0)
    assert t.problems(duration=1.0) == []
