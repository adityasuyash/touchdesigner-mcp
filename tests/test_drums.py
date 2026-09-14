"""Finding the drums, and the grid they sit on.

What TouchDesigner calls `kick` and `snare` are RMS *level* thresholds on two
broad bands of the whole mix. Measured live over 44.8s of playback, the phase of
their rising edges within the beat had a circular concentration of 0.12 and 0.15
-- statistically indistinguishable from uniform. They were never late; they were
never beat-locked at all, because a level threshold on a band holding a
sustained bassline crosses on bass notes and stays crossed while they sustain.

And what it calls `snare` is a 3500 Hz highpass -- hats, cymbals and sibilance.
There has never been a snare detector anywhere in this project.
"""

from __future__ import annotations

import numpy as np
import pytest

from lyricfield import analysis as A


def _score(truth, got, tol=0.05):
    got, hits = list(got), []
    for t in truth:
        near = [g for g in got if abs(g - t) <= tol]
        if near:
            g = min(near, key=lambda v: abs(v - t))
            hits.append(g - t)
            got.remove(g)
    return len(hits), len(got), (float(np.mean(hits)) if hits else float("nan"))


# --------------------------------------------------------- the detectors

def test_kicks_are_found_where_they_were_placed(drum_audio):
    x, kicks, _, _ = drum_audio
    hit, spurious, bias = _score(kicks, A.detect_kicks(x))
    assert hit >= len(kicks) - 1, f"found only {hit} of {len(kicks)}"
    assert spurious <= len(kicks) // 2
    assert abs(bias) < 0.030, f"kicks reported {bias*1000:+.0f} ms out"


def test_snares_are_found_at_all(drum_audio):
    """The channel this replaces is a 3500 Hz highpass, which a snare barely
    reaches -- its body is 180-700 Hz."""
    x, _, snares, _ = drum_audio
    hit, spurious, bias = _score(snares, A.detect_snares(x))
    assert hit == len(snares), f"found only {hit} of {len(snares)}"
    assert abs(bias) < 0.030


def test_hats_are_found(drum_audio):
    x, _, _, hats = drum_audio
    hit, _spurious, bias = _score(hats, A.detect_hats(x))
    assert hit >= len(hats) * 0.85
    assert abs(bias) < 0.030


def test_a_sustained_bassline_is_not_mistaken_for_kicks(drum_audio):
    """The whole reason for using flux rather than level. The fixture plays a
    55 Hz bassline under the kit; a level gate fires on its note changes and
    sustain, which is what made the live gates phase-uniform."""
    x, kicks, _, _ = drum_audio
    got = A.detect_kicks(x)
    assert len(got) < len(kicks) * 2, (
        f"{len(got)} kicks reported where {len(kicks)} were played")


def test_a_snares_crack_is_not_also_reported_as_a_hat(drum_audio):
    """A snare lands in the hats' band too. `detect_drums` is the entry point
    precisely because the three have to be de-conflicted against each other."""
    x, _, _, _ = drum_audio
    alone = A.detect_hats(x)
    drums = A.detect_drums(x)
    assert len(drums["hat"]) < len(alone), "nothing was suppressed"
    # Against the snares it actually found, which is what it de-conflicts
    # against -- asserting against the ground truth instead would be testing
    # the snare detector's accuracy here rather than the suppression.
    for h in drums["hat"]:
        assert min(abs(h - s) for s in drums["snare"]) > 0.04


def test_silence_yields_no_drums():
    assert A.detect_drums(np.zeros(A.SR * 3, np.float32)) == {
        "kick": [], "snare": [], "hat": []}


# ------------------------------------------------------------ the grid

def test_the_fitted_period_beats_the_autocorrelation_grid():
    """`estimate_tempo` reads its period off an autocorrelation lag in whole
    frames, so at 100 fps it can only return a multiple of 10 ms. That is not a
    rounding nicety: on a real 162s track the 1.6 ms/beat error accumulated to
    0.39 of a beat by the end, so a crest timed to the grid finishes half a beat
    away from the music it started with."""
    period = 0.6684                      # deliberately between two frame lags
    strikes = [round(0.137 + i * period, 4) for i in range(200)]
    got, anchor = A.fit_beat_grid(strikes, 0.67)
    assert abs(got - period) < 0.0005, f"fitted {got}, wanted {period}"
    drift = abs(0.67 - period) * (len(strikes))
    assert drift > 0.3, "the fixture no longer demonstrates the problem"


def test_the_anchor_comes_out_of_the_same_fit():
    period, first = 0.5, 0.137
    strikes = [round(first + i * period, 4) for i in range(120)]
    _got, anchor = A.fit_beat_grid(strikes, 0.5)
    assert abs((anchor - first) % period) < 0.02 or \
        abs(((anchor - first) % period) - period) < 0.02


def test_fitting_needs_something_to_fit():
    assert A.fit_beat_grid([], 0.5) == (0.5, 0.0)
    assert A.fit_beat_grid([1.0, 2.0], 0.5) == (0.5, 0.0)


def test_the_fit_locks_the_pattern_better_than_the_raw_estimate(drum_audio):
    """The end-to-end claim, on the synthesised kit."""
    x, _kicks, _, _ = drum_audio
    got = A.detect_kicks(x)
    p0, _bpm = A.estimate_tempo(x)
    p1, _a = A.fit_beat_grid(got, p0)

    def lock(times, period):
        return float(abs(np.exp(2j * np.pi * (np.array(times) % period) / period).mean()))

    assert lock(got, p1) >= lock(got, p0)
