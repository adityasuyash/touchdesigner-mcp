"""The shipped looks must be tellable apart, and must actually hit.

Measured, the previous five were about two and a half pictures: cascade and
shimmer correlated at 0.82 on both mean level and lit-count, sweep and cascade
at 0.62. Every one of them sat at the type's default `level_min`/`level_max`/
`ceil` and at the default of all nine glow and bloom values, and none had moved
`lit_at` -- the hard threshold where a cell leaves the dim layer for the bold
one, gaining the white alpha, the bold face and a tight bloom at once. So they
differed in how much and what colour, rather than in what they did.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.styles import list_styles

BEAT = 0.5
PULSE = [st for st in list_styles() if st.type == "pulse_grid"]
BEATSYNC = [st for st in list_styles()
            if types_mod.get_type(st.type).family == types_mod.BEATSYNC]


def _run(st, secs=16.0, fps=30.0):
    """Cook a style over a synthetic bar and report what the frame did."""
    src = types_mod.get_type(st.type).field_source()
    m = pytypes.ModuleType("under_test")
    m.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), m.__dict__)
    for section in st.params.__dataclass_fields__:
        for k, v in vars(getattr(st.params, section)).items():
            if k in m.DEFAULTS:
                m.__dict__[k.upper()] = v
    m.BEAT = m.BEAT_PERIOD = BEAT
    m.BEAT_ANCHOR = 0.0
    if "GLYPHS" in m.__dict__:
        m.__dict__["RAMP"] = np.array(list(m.GLYPHS))
    m.S["rng"] = np.random.default_rng(7)
    m._init()

    kicks = list(np.arange(0.0, secs, BEAT * 2))
    snares = list(np.arange(BEAT, secs, BEAT * 2))
    hats = list(np.arange(0.0, secs, BEAT / 2))
    m.S["drums"] = {"kick": kicks, "snare": snares, "hat": hats}

    lit, mean, motion, prev = [], [], [], None
    for i in range(1, int(secs * fps)):
        t, pt = i / fps, (i - 1) / fps
        m.S["since_t"], m.S["last_t"] = pt, t
        k = float(any(pt < x <= t for x in kicks))
        sn = float(any(pt < x <= t for x in snares))
        hi = float(any(pt < x <= t for x in hats))
        v, is_lit = _value(m, t, k, sn, hi)
        lit.append(float(is_lit.mean()))
        mean.append(float(v.mean()))
        if prev is not None:
            motion.append(float(np.abs(v - prev).mean()))
        prev = v
    return (np.array(lit), np.array(mean), np.array(motion))


def _value(m, t, kick, snare, high):
    """The per-cell value and which cells are bold, for either beatsync type."""
    if hasattr(m, "_weights"):                       # swell
        w = m._weights(t, kick, snare, high)
        v = m.LEVEL_MIN + (m.LEVEL_MAX - m.LEVEL_MIN) * w
        return v, (w >= m.LIT_AT) & (w > 0)
    rows, cols = m.BAND, m.COLS                      # pulse_grid
    span = max(1e-6, m.BEAT * m.WAVE_BEATS)
    phase = ((t - m.BEAT_ANCHOR) % span) / span
    axis = rows if m.VERTICAL else cols
    crest = phase * (axis + m.WAVE_WIDTH * 2) - m.WAVE_WIDTH
    line = np.arange(axis, dtype=np.float32)
    shape = np.exp(-0.5 * (np.abs(line - crest) / max(0.3, m.WAVE_WIDTH)) ** 2)
    wave = (shape[:, None] * np.ones((1, cols), np.float32) if m.VERTICAL
            else np.ones((rows, 1), np.float32) * shape[None, :])
    base = m.LEVEL_MIN + (m.LEVEL_MAX - m.LEVEL_MIN) * m.S["bias"]
    v = base + m.WAVE_LIFT * wave
    if kick:
        v = v + m.KICK_LIFT * 0.8
    if snare:
        room = np.maximum(1e-6, (m.CEIL + m.WAVE_LIFT) - base)
        v = v + m.SNARE_PEAK * m.SNARE_FRAC * 6.0 * room
    if high:
        v = v + m.HIGH_LIFT * m.S["bias"]
    v = np.clip(v, 0.0, m.CEIL + m.WAVE_LIFT)
    blank = m.S["chars"] == " "
    v = np.where(blank, 0.0, v)
    return v, (v >= m.LIT_AT) & (~blank)


# ------------------------------------------------------------- distinctness

def test_no_two_beatsync_looks_measure_the_same():
    """Correlating each pair's lit-count series: two looks that rise and fall
    together are one look in two colours."""
    series = {st.slug: _run(st)[0] for st in PULSE}
    worst, pair = -1.0, None
    for a in series:
        for b in series:
            if a >= b:
                continue
            x, y = series[a], series[b]
            if x.std() < 1e-9 or y.std() < 1e-9:
                continue
            r = float(np.corrcoef(x, y)[0, 1])
            if r > worst:
                worst, pair = r, (a, b)
    assert worst < 0.75, f"{pair} still move together (r={worst:.2f})"


def test_each_look_leads_with_a_different_driver():
    """Sweep by its crest, Heartbeat by the kick, Shimmer by the hats. If two
    lead with the same one they are the same idea."""
    leads = {}
    for st in PULSE:
        p = st.params.pulse
        leads[st.slug] = max(
            (("wave", p.wave_lift), ("kick", p.kick_lift),
             ("snare", p.snare_peak * p.snare_frac * 6.0), ("high", p.high_lift)),
            key=lambda kv: kv[1])[0]
    assert len(set(leads.values())) >= 3, f"only {set(leads.values())}: {leads}"


# ------------------------------------------------------------------ punch

@pytest.mark.parametrize("st", PULSE, ids=[s.slug for s in PULSE])
def test_a_look_starts_dark_enough_for_a_strike_to_show(st):
    """The recipe that makes a beat read as an event rather than a baseline:
    the resting field must sit well below the threshold, so crossing it means
    something. Raising the lifts alone just promotes more of the field."""
    lk, p = st.params.look, st.params.pulse
    assert lk.level_max < p.lit_at, (
        f"{st.slug}: the base reaches {lk.level_max}, at or past the "
        f"{p.lit_at} threshold — cells are lit before anything is struck")


@pytest.mark.parametrize("st", PULSE, ids=[s.slug for s in PULSE])
def test_a_look_uses_the_glow_it_was_given(st):
    """All nine glow and bloom values were at their default in every shipped
    style — the whole crisp-versus-hazy axis, unexplored."""
    from lyricfield.types.lyric_grid.params import Look
    d = Look()
    lk = st.params.look
    moved = sum(1 for f in ("glow_base", "glow_radius", "bloom_bright", "bloom_size")
                if abs(getattr(lk, f) - getattr(d, f)) > 1e-6)
    assert moved >= 2, f"{st.slug} left the glow chain at its defaults"


def test_the_beat_renderer_that_had_no_styles_has_some():
    swell = [st for st in BEATSYNC if st.type == "swell"]
    assert swell, "swell still ships no styles, so it has no tile to pick"
