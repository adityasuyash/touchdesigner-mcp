"""A strike in the table must move the picture on the frame it lands.

The old path could not do this. `kick` and `snare` were RMS level gates on two
broad bands of the whole mix, evaluated per frame; a sustained bassline crosses
such a gate and stays across it, so the events bore no relation to the drums --
measured live over 44.8 seconds, the phase of their rising edges within the beat
had a circular concentration of 0.12, which is uniform.

The times here are deliberately IRREGULAR. A regular grid can only ever reveal
a timing error modulo one beat, which is exactly how this hid: correlating a
shipped preview against its song's beat grid put the best match at +0.667s --
one whole beat period.
"""

from __future__ import annotations

import numpy as np
import pytest

from lyricfield.drums import DrumTable, Hit, fired

FPS = 60.0
STRIKES = [0.31, 0.94, 1.83, 2.20, 3.47, 4.02, 5.51, 6.19]


# ------------------------------------------------------- the lookup itself

def test_a_strike_is_reported_on_exactly_one_frame():
    """Once, however the frame rate moves -- that is what lets the beatsync
    types drop the beat-cell throttle that dropped 17% of their kicks."""
    times = sorted(STRIKES)
    for rate in (24.0, 30.0, 60.0, 120.0):
        hits = 0
        for i in range(1, int(7.0 * rate)):
            if fired(times, i / rate, (i - 1) / rate):
                hits += 1
        assert hits == len(times), f"at {rate} fps: {hits} of {len(times)}"


def test_a_strike_is_reported_on_the_frame_it_lands():
    times = sorted(STRIKES)
    for s in times:
        frame = int(np.ceil(s * FPS))
        assert fired(times, frame / FPS, (frame - 1) / FPS)
        assert not fired(times, (frame + 1) / FPS, frame / FPS)


def test_nothing_fires_in_an_empty_table():
    assert not fired([], 1.0, 0.0)
    assert not fired([5.0], 1.0, 0.0)


def test_a_backward_scrub_reports_nothing():
    assert not fired(sorted(STRIKES), 0.5, 2.0)


# -------------------------------------------------- through the renderer

def _drum_dat(kind_times):
    return DrumTable([Hit(k, t) for k, ts in kind_times.items() for t in ts])


@pytest.mark.parametrize("at", STRIKES[:4])
def test_a_kick_in_the_table_moves_the_picture(cooker, at):
    """End to end through `onCook`: the frame containing the strike must differ
    from the frame before it, and it must be the frame that contains it."""
    drums = {"kick": STRIKES, "snare": [], "hat": []}
    frame = int(np.ceil(at * FPS))
    before = cooker((frame - 1) / FPS, drums=drums, back_level=0.05,
                    back_wave=1.0, ambient_target=60)
    on = cooker(frame / FPS, drums=drums, back_level=0.05,
                back_wave=1.0, ambient_target=60)
    assert on["stats"]["rings"] > before["stats"]["rings"], (
        f"no ring spawned for the kick at {at}s "
        f"({before['stats']['rings']} -> {on['stats']['rings']})")


def test_a_quiet_stretch_spawns_nothing(cooker):
    drums = {"kick": [9.0], "snare": [], "hat": []}
    r = cooker(2.0, drums=drums, back_level=0.05, back_wave=1.0, ambient_target=60)
    assert r["stats"]["rings"] == 0


def test_the_table_survives_the_dat_round_trip():
    t = _drum_dat({"kick": STRIKES, "snare": [1.1], "hat": [0.2, 0.4]})
    back = DrumTable.from_dat_text(t.to_dat_text())
    assert back.times("kick") == sorted(STRIKES)
    assert back.counts() == t.counts()


def test_a_table_with_nothing_in_it_says_so():
    assert "no drum hits" in "; ".join(DrumTable().problems())


def test_hits_past_the_end_are_reported():
    t = _drum_dat({"kick": [1.0, 400.0]})
    assert any("past the end" in p for p in t.problems(duration=120.0))


# ------------------------------------------------- the ring must hit on time

def _ring_energy(field_mod, ages):
    """Total ring brightness at each age, from the field's own maths."""
    m = field_mod
    maxr = float(np.hypot(m.BAND, m.COLS))
    gr, gc = np.mgrid[0:m.VROWS, 0:m.COLS]
    d = np.sqrt((gr - m.BAND // 2) ** 2 + (gc - m.COLS // 2) ** 2)
    out = []
    for age in ages:
        rad = 2.0 * m.RIPPLE_SIGMA + (age / m.RIPPLE_TIME) * maxr
        amp = m.RIPPLE_LIFT * max(0.0, 1.0 - age / (m.RIPPLE_TIME * 1.35))
        out.append(float((amp * np.exp(-((d - rad) / m.RIPPLE_SIGMA) ** 2)).sum()))
    return np.array(out)


def test_the_kick_ring_is_brightest_near_the_strike(field_mod):
    """It used to be brightest 167 ms after the kick.

    The ring was born as a single point and only became bright as it expanded,
    so the hit arrived long after the sound -- measured at +200 ms in a
    delivered file by isolating the backdrop's colour from the words'. The
    detector was never the problem; the drawing was.
    """
    ages = np.arange(0.0, field_mod.RIPPLE_TIME * 1.35, 1 / 120.0)
    e = _ring_energy(field_mod, ages)
    peak_at = ages[int(np.argmax(e))]
    half_at = ages[int(np.argmax(e >= e.max() * 0.5))]
    assert half_at <= 0.030, f"half brightness only at {half_at*1000:.0f} ms"
    assert peak_at <= 0.100, f"peak at {peak_at*1000:.0f} ms, still late"


def test_the_ring_is_visible_the_instant_it_is_struck(field_mod):
    """At age zero it used to light about one cell -- a tenth of what it would
    become."""
    e = _ring_energy(field_mod, np.array([0.0]))
    peak = _ring_energy(field_mod, np.arange(0.0, 0.4, 1 / 120.0)).max()
    assert e[0] >= peak * 0.5, (
        f"only {e[0]/peak:.0%} of the ring is there when the kick lands")


def test_the_look_is_unchanged_only_the_timing(field_mod):
    """A brighter or wider ring would be a different look, not a fixed one."""
    m = field_mod
    ages = np.arange(0.0, m.RIPPLE_TIME * 1.35, 1 / 120.0)
    maxr = float(np.hypot(m.BAND, m.COLS))
    gr, gc = np.mgrid[0:m.VROWS, 0:m.COLS]
    d = np.sqrt((gr - m.BAND // 2) ** 2 + (gc - m.COLS // 2) ** 2)
    brightest = 0.0
    for age in ages:
        rad = 2.0 * m.RIPPLE_SIGMA + (age / m.RIPPLE_TIME) * maxr
        amp = m.RIPPLE_LIFT * max(0.0, 1.0 - age / (m.RIPPLE_TIME * 1.35))
        brightest = max(brightest,
                        float((amp * np.exp(-((d - rad) / m.RIPPLE_SIGMA) ** 2)).max()))
    assert brightest <= m.RIPPLE_LIFT + 1e-6
    assert brightest >= m.RIPPLE_LIFT * 0.95
