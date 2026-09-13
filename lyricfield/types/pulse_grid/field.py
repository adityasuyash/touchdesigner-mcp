# Runs INSIDE TouchDesigner as the Script TOP callbacks for the pulse_grid type.
# Not importable standalone in TD terms: it depends on TD globals (op, root, me)
# and is synced into the .toe by lyricfield.sync. Edit it here, in the repo.
#
# Outputs at COLS x VROWS, one pixel per grid cell:
#   RGB   = the DIM layer's colour for that cell
#   ALPHA = the LIT layer's weight (drives the bold text layer)
# and writes two character DATs, exactly as the lyric type does, so both share
# one network and one glow chain.
#
# THE BEAT IS EXPRESSED ONLY AS LIGHT. Nothing scales and no glyph moves; what
# travels is brightness.
#   PULSE -> a crest sweeps the field, timed to the measured beat grid rather
#            than free-running, so it lands with the track.
#   KICK  -> a radial ripple expands from a point.
#   SNARE -> a scatter of cells spikes and decays.
#   HIGH  -> a shimmer across the whole field.
#
# This type needs no lyrics, which is the point of it: a song with no vocals
# used to render a black frame for its whole length.

import numpy as np

DEFAULTS = {
    # grid
    'cols': 24, 'vrows': 24, 'band': 22, 'band_top': 1,
    # look (shared with lyric_grid -- same network, same glow chain)
    'dim_hue': 0.58, 'dim_sat': 0.35,
    'level_min': 0.10, 'level_max': 0.38, 'ceil': 0.58,
    'drift_min': 3.0, 'drift_max': 6.0,
    # pulse
    'wave_beats': 4.0, 'wave_width': 3.5, 'wave_lift': 0.34,
    'vertical': False, 'density': 0.72, 'glyphs': '.:-=+*#',
    'lit_at': 0.52,
    'kick_lift': 0.26, 'kick_time': 0.55, 'kick_sigma': 2.2,
    'snare_frac': 0.06, 'snare_peak': 0.5, 'snare_time': 0.25,
    'high_lift': 0.18, 'reroll': 12.0,
    # Track structure, measured per song. Neutral, never a particular song's
    # numbers -- a fallback that is convincingly wrong is worse than one that is
    # obviously wrong.
    'beat_anchor': 0.0, 'beat_period': 0.5, 'kick_in': 0.0, 'high_in': 0.0,
    'hold_windows': (), 'duration': 0.0,
}

PARAMS_DAT = 'params'
DIM_DAT = 'v7_chars_dim'
LIT_DAT = 'v7_chars_lit'
ANALYSIS_CHOP = 'v6_aa'

S = {}
PARAMS_MISSING = False


def _params_text():
    d = op(PARAMS_DAT)
    return d.text if d is not None else ''


def _load_params():
    global PARAMS_MISSING
    try:
        p = dict(mod(PARAMS_DAT).P)
        PARAMS_MISSING = not p
        return p
    except Exception:
        PARAMS_MISSING = True
        return {}


def _apply_params():
    P = _load_params()
    g = globals()
    for key, fallback in DEFAULTS.items():
        g[key.upper()] = P.get(key, fallback)
    for key in ('cols', 'vrows', 'band', 'band_top'):
        g[key.upper()] = int(g[key.upper()])
    dur = float(P.get('duration') or 0.0)
    if dur <= 0.0:
        try:
            dur = float(root.time.end) / float(root.time.rate)
        except Exception:
            dur = 0.0
    g['TAIL_END'] = dur
    g['BEAT'] = max(1e-3, float(g['BEAT_PERIOD']))
    return P


_apply_params()


def _smooth(a):
    a = min(1.0, max(0.0, a))
    return a * a * (3.0 - 2.0 * a)


def _hsv(h, s, v):
    i = int(h * 6.0) % 6
    f = h * 6.0 - int(h * 6.0)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    return [(v, t, p), (q, v, p), (p, v, t),
            (p, q, v), (t, p, v), (v, p, q)][i]


def _held(t):
    for a, b in HOLD_WINDOWS:
        if a <= t < b:
            return True
    return False


def _init():
    """Scatter the glyphs. Re-rolled every `reroll` seconds so the field keeps
    changing without anything ever moving."""
    rng = S.get('rng') or np.random.default_rng()
    S['rng'] = rng
    rows, cols = BAND, COLS
    keep = rng.random((rows, cols)) < DENSITY
    idx = rng.integers(0, len(GLYPHS), size=(rows, cols))
    S['chars'] = np.where(keep, np.array(list(GLYPHS))[idx], ' ')
    # a per-cell brightness offset, so the field is not a flat plane
    S['bias'] = rng.random((rows, cols)).astype(np.float32)
    S['rolled'] = S.get('t', 0.0)
    S['sparks'] = np.full((rows, cols), -1.0e9, np.float32)
    S['rings'] = []
    S['beat_i'] = -1


def onSetupParameters(scriptOp):
    page = scriptOp.appendCustomPage('Pulse')
    page.appendFloat('Cueoffset', label='Cue offset')
    return


def onPulse(par):
    return


def onCook(scriptOp):
    pkey = _params_text()
    if 'chars' not in S or S.get('pkey') != pkey:
        _apply_params()
        _init()
        S['pkey'] = pkey

    t = root.time.seconds
    S['t'] = t
    prev = S.get('last_t', -1.0)
    if prev < 0 or t < prev:                 # first cook, or a backward scrub
        _init()
    S['last_t'] = t

    if REROLL > 0 and t - S.get('rolled', 0.0) > REROLL:
        _init()

    rows, cols = BAND, COLS
    held = _held(t)

    aa = op(ANALYSIS_CHOP)
    kick = float(aa['kick'].eval()) if aa else 0.0
    snare = float(aa['snare'].eval()) if aa else 0.0
    high = float(aa['high'].eval()) if aa else 0.0

    # ---- the sweep, on the measured beat grid -------------------------------
    # Phase runs 0..1 over `wave_beats` beats, anchored to the track's own
    # downbeat, so the crest arrives with the music instead of drifting.
    span = max(1e-6, BEAT * WAVE_BEATS)
    phase = ((t - BEAT_ANCHOR) % span) / span
    axis = rows if VERTICAL else cols
    crest = phase * (axis + WAVE_WIDTH * 2) - WAVE_WIDTH

    line = np.arange(rows if VERTICAL else cols, dtype=np.float32)
    d = np.abs(line - crest)
    shape = np.exp(-0.5 * (d / max(0.3, WAVE_WIDTH)) ** 2).astype(np.float32)
    wave = shape[:, None] * np.ones((1, cols), np.float32) if VERTICAL else \
        np.ones((rows, 1), np.float32) * shape[None, :]

    # ---- kick ripples -------------------------------------------------------
    if not held and kick > 0.5:
        bi = int(np.floor((t - BEAT_ANCHOR) / BEAT))
        if bi != S.get('beat_i'):
            S['beat_i'] = bi
            rng = S['rng']
            S['rings'].append((t, int(rng.integers(0, rows)), int(rng.integers(0, cols))))
    S['rings'] = [r for r in S['rings'] if t - r[0] < KICK_TIME]

    ripple = np.zeros((rows, cols), np.float32)
    if S['rings'] and not held:
        rr, cc = np.mgrid[0:rows, 0:cols]
        for t0, r0, c0 in S['rings']:
            age = (t - t0) / max(1e-6, KICK_TIME)
            radius = age * max(rows, cols) * 0.7
            dist = np.sqrt((rr - r0) ** 2 + (cc - c0) ** 2)
            ring = np.exp(-0.5 * ((dist - radius) / KICK_SIGMA) ** 2)
            ripple = np.maximum(ripple, (ring * (1.0 - age)).astype(np.float32))

    # ---- snare sparks -------------------------------------------------------
    if not held and snare > 0.5:
        rng = S['rng']
        n = max(1, int(rows * cols * SNARE_FRAC))
        flat = rng.choice(rows * cols, size=n, replace=False)
        S['sparks'].flat[flat] = t
    spark_age = (t - S['sparks']) / max(1e-6, SNARE_TIME)
    sparks = np.where((spark_age >= 0) & (spark_age < 1.0),
                      (1.0 - spark_age), 0.0).astype(np.float32)

    # ---- compose ------------------------------------------------------------
    base = LEVEL_MIN + (LEVEL_MAX - LEVEL_MIN) * S['bias']
    v = base + WAVE_LIFT * wave + KICK_LIFT * ripple
    v = np.maximum(v, SNARE_PEAK * sparks)
    if not held and HIGH_LIFT > 0 and high > 0.0:
        v = v + HIGH_LIFT * min(1.0, high) * S['bias']
    v = np.clip(v, 0.0, CEIL + WAVE_LIFT)

    blank = S['chars'] == ' '
    v = np.where(blank, 0.0, v)

    lit_mask = (v >= LIT_AT) & (~blank)
    # Nothing that is not the crest reaches 1.0, exactly as in the lyric type.
    alpha = np.where(lit_mask, np.clip(v / max(1e-6, CEIL + WAVE_LIFT), 0.0, 1.0), 0.0)

    rgb = np.zeros((VROWS, COLS, 3), np.float32)
    out_alpha = np.zeros((VROWS, COLS), np.float32)
    dim_ch = np.full((VROWS, COLS), ' ', dtype='<U1')
    lit_ch = np.full((VROWS, COLS), ' ', dtype='<U1')

    for r in range(rows):
        R = BAND_TOP + r
        for c in range(cols):
            ch = S['chars'][r, c]
            if ch == ' ':
                continue
            level = float(v[r, c])
            if lit_mask[r, c]:
                lit_ch[R, c] = ch
                out_alpha[R, c] = float(alpha[r, c])
            else:
                dim_ch[R, c] = ch
                cr, cg, cb = _hsv(DIM_HUE, DIM_SAT, min(CEIL, level))
                rgb[R, c, 0], rgb[R, c, 1], rgb[R, c, 2] = cr, cg, cb

    S['stats'] = {'lit': int(lit_mask.sum()), 'rings': len(S['rings']),
                  'held': bool(held), 'phase': round(float(phase), 3)}

    op(DIM_DAT).text = '\n'.join(''.join(row) for row in dim_ch)
    op(LIT_DAT).text = '\n'.join(''.join(row) for row in lit_ch)

    out = np.empty((VROWS, COLS, 4), np.float32)
    out[:, :, 0:3] = rgb
    out[:, :, 3] = out_alpha
    scriptOp.copyNumpyArray(np.ascontiguousarray(np.flipud(out)))
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS       # no input; must run every frame
