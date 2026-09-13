# Runs INSIDE TouchDesigner as the Script TOP callbacks for the swell type.
# Not importable standalone in TD terms: it depends on TD globals (op, root, me)
# and is synced into the .toe by lyricfield.sync. Edit it here, in the repo.
#
# Outputs at COLS x VROWS, one pixel per grid cell:
#   RGB   = the DIM layer's colour for that cell
#   ALPHA = the LIT layer's weight (drives the bold text layer)
# and writes two character DATs, exactly as the other two types do, so all three
# share one network and one glow chain.
#
# THE BEAT IS EXPRESSED AS WEIGHT AND COVERAGE, NOT BRIGHTNESS. `pulse_grid`
# holds a fixed scatter of glyphs and lights parts of it; this holds one
# coverage number and moves that. A cell carries a glyph when its fixed random
# bias falls under the current coverage, and the further under, the heavier the
# glyph on the ramp `.:-=+*#`. So a rise fills blanks in AND thickens what is
# already there, from a single value, with nothing moving and nothing scaling.
#
# The consequence worth having: the brightest cell on the loudest beat is no
# brighter than the dimmest cell in the quietest bar. The dim layer never leaves
# level_min..level_max, so the stacking rule that constrains every other
# renderer cannot be breached here, and the glow chain amplifies the shape
# instead of clipping it.
#
#   SWELL -> coverage rises fast on the downbeat and thins across the bar.
#   KICK  -> a ring of extra weight expands from a point.
#   SNARE -> a scatter of cells jumps to the top of the ramp.
#   HIGH  -> the hi-hats roughen the weight field, both ways.
#
# It is also the first renderer to read the three measured facts every beatsync
# type had been ignoring: it is sparse before `kick_in`, opens up at `high_in`,
# and thins to nothing over the last `outro` seconds of `duration`. Without
# those the piece has no beginning, no arrival and no ending.

import numpy as np

DEFAULTS = {
    # grid
    'cols': 24, 'vrows': 24, 'band': 22, 'band_top': 1,
    # look (shared with the other types -- same network, same glow chain)
    'dim_hue': 0.58, 'dim_sat': 0.35,
    'level_min': 0.10, 'level_max': 0.38, 'ceil': 0.58,
    'drift_min': 3.0, 'drift_max': 6.0,
    # swell
    'bar_beats': 4.0, 'attack': 0.14,
    'open_min': 0.16, 'open_max': 0.84,
    'glyphs': '.:-=+*#', 'lit_at': 0.78,
    'intro_open': 0.30, 'arrive': 0.78, 'outro': 14.0,
    'kick_open': 0.30, 'kick_time': 0.55, 'kick_sigma': 2.4,
    'snare_frac': 0.07, 'snare_time': 0.28,
    'high_grain': 0.22, 'reroll': 16.0,
    # Track structure, measured per song. Neutral, never a particular song's
    # numbers -- a fallback that is convincingly wrong is worse than one that is
    # obviously wrong.
    'beat_anchor': 0.0, 'beat_period': 0.5, 'kick_in': 0.0, 'high_in': 0.0,
    'hold_windows': (), 'duration': 0.0,
}

# How long the field takes to open at a section boundary. Not a tunable: it is
# a perceptual constant, and a knob nothing needs is a knob that goes wrong.
INTRO_RAMP = 2.0

# The weight below which a cell stays blank. Without it the kick ring's
# Gaussian tail -- which never actually reaches zero -- painted the lightest
# glyph across the entire frame on every kick, turning a ring into a flat wash
# of dots. Not a tunable either: it is where floating-point dust stops counting
# as ink.
INK = 0.04

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
    g['RAMP'] = np.array(list(g['GLYPHS']))
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


def _section_gain(t):
    """Where in the piece this is, as a multiplier on coverage.

    Sparse before the drums, most of the way open once they are in, fully open
    once the hi-hats arrive, and thinning to nothing over the outro. A song
    whose analysis found no kick gets a flat 1.0 rather than a guess.
    """
    g = 1.0
    if KICK_IN > 0.0 and t < KICK_IN:
        g = INTRO_OPEN + (1.0 - INTRO_OPEN) * _smooth(
            (t - (KICK_IN - INTRO_RAMP)) / INTRO_RAMP)
    elif HIGH_IN > KICK_IN and t < HIGH_IN:
        g = ARRIVE + (1.0 - ARRIVE) * _smooth(
            (t - (HIGH_IN - INTRO_RAMP)) / INTRO_RAMP)
    if TAIL_END > 0.0 and OUTRO > 0.0:
        g *= _smooth((TAIL_END - t) / OUTRO)
    return max(0.0, min(1.0, g))


def _coverage(t):
    """How much of the field is occupied at this instant.

    One number, on the measured beat grid so it lands with the track: a quick
    rise over `attack` of the bar, then a slide back across the rest of it.
    """
    span = max(1e-6, BEAT * BAR_BEATS)
    ph = ((t - BEAT_ANCHOR) % span) / span
    a = _smooth(ph / ATTACK) if ph < ATTACK else \
        1.0 - _smooth((ph - ATTACK) / max(1e-6, 1.0 - ATTACK))
    return (OPEN_MIN + (OPEN_MAX - OPEN_MIN) * a) * _section_gain(t)


def _init():
    """Lay down the two fixed random fields.

    `bias` is what coverage is compared against, so it decides the order in
    which cells fill in -- fixed, or the field would boil. `grain` is what the
    hi-hats roughen. Re-rolled every `reroll` seconds so the arrangement keeps
    changing between swells without anything ever moving within one.
    """
    rng = S.get('rng') or np.random.default_rng()
    S['rng'] = rng
    rows, cols = BAND, COLS
    S['bias'] = rng.random((rows, cols)).astype(np.float32)
    S['grain'] = rng.random((rows, cols)).astype(np.float32)
    S['rolled'] = S.get('t', 0.0)
    S['sparks'] = np.full((rows, cols), -1.0e9, np.float32)
    S['rings'] = []
    S['beat_i'] = -1


def _weights(t, kick=0.0, snare=0.0, high=0.0):
    """The per-cell weight, 0 (blank) to 1 (heaviest glyph on the ramp)."""
    rows, cols = BAND, COLS
    held = _held(t)
    cover = _coverage(t)
    gain = _section_gain(t)

    # How far under the coverage a cell's bias sits, against a FIXED spread --
    # not against the coverage itself. Normalising by coverage was the first
    # version and it was wrong in a way that looked right: the number of drawn
    # cells moved, but their weights stayed uniformly spread whatever the
    # coverage, so the mean position on the ramp did not move at all and the
    # renderer was expressing density alone. Dividing by a constant makes a rise
    # do both -- more cells, and heavier ones.
    w = (cover - S['bias']) / max(1e-6, OPEN_MAX)
    w = np.clip(w, 0.0, 1.0).astype(np.float32)

    # kick: a ring of extra weight, so blanks fill in along it
    if not held and kick > 0.5:
        bi = int(np.floor((t - BEAT_ANCHOR) / BEAT))
        if bi != S.get('beat_i'):
            S['beat_i'] = bi
            rng = S['rng']
            S['rings'].append(
                (t, int(rng.integers(0, rows)), int(rng.integers(0, cols))))
    S['rings'] = [r for r in S['rings'] if t - r[0] < KICK_TIME]
    if S['rings'] and not held and KICK_OPEN > 0:
        rr, cc = np.mgrid[0:rows, 0:cols]
        for t0, r0, c0 in S['rings']:
            age = (t - t0) / max(1e-6, KICK_TIME)
            radius = age * max(rows, cols) * 0.7
            dist = np.sqrt((rr - r0) ** 2 + (cc - c0) ** 2)
            ring = np.exp(-0.5 * ((dist - radius) / KICK_SIGMA) ** 2)
            w = w + (KICK_OPEN * gain * (1.0 - age) * ring).astype(np.float32)

    # snare: a scatter jumps to the top of the ramp and falls back
    if not held and snare > 0.5 and SNARE_FRAC > 0:
        rng = S['rng']
        n = max(1, int(rows * cols * SNARE_FRAC))
        S['sparks'].flat[rng.choice(rows * cols, size=n, replace=False)] = t
    age = (t - S['sparks']) / max(1e-6, SNARE_TIME)
    spark = np.where((age >= 0) & (age < 1.0), 1.0 - age, 0.0).astype(np.float32)
    w = np.maximum(w, spark * gain)

    # hi-hats: roughen it both ways, so the texture moves without the field
    # simply getting fuller
    if not held and HIGH_GRAIN > 0 and high > 0.0:
        w = w + HIGH_GRAIN * min(1.0, high) * (S['grain'] - 0.5) * 2.0

    w = np.clip(w, 0.0, 1.0).astype(np.float32)
    return np.where(w < INK, 0.0, w).astype(np.float32)


def onSetupParameters(scriptOp):
    page = scriptOp.appendCustomPage('Swell')
    page.appendFloat('Cueoffset', label='Cue offset')
    return


def onPulse(par):
    return


def onCook(scriptOp):
    pkey = _params_text()
    if 'bias' not in S or S.get('pkey') != pkey:
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

    aa = op(ANALYSIS_CHOP)
    kick = float(aa['kick'].eval()) if aa else 0.0
    snare = float(aa['snare'].eval()) if aa else 0.0
    high = float(aa['high'].eval()) if aa else 0.0

    w = _weights(t, kick, snare, high)
    rows, cols = BAND, COLS

    # The glyph IS the signal: index into the ramp by weight.
    steps = len(RAMP) - 1
    idx = np.clip(np.rint(w * steps).astype(int), 0, steps)
    chars = np.where(w > 0.0, RAMP[idx], ' ')

    # Brightness follows weight only within the dim layer's own band, so the
    # loudest beat is no brighter than the quietest bar and nothing can clip.
    v = LEVEL_MIN + (LEVEL_MAX - LEVEL_MIN) * w
    lit_mask = (w >= LIT_AT) & (chars != ' ')

    rgb = np.zeros((VROWS, COLS, 3), np.float32)
    out_alpha = np.zeros((VROWS, COLS), np.float32)
    dim_ch = np.full((VROWS, COLS), ' ', dtype='<U1')
    lit_ch = np.full((VROWS, COLS), ' ', dtype='<U1')

    for r in range(rows):
        R = BAND_TOP + r
        for c in range(cols):
            ch = chars[r, c]
            if ch == ' ':
                continue
            if lit_mask[r, c]:
                lit_ch[R, c] = ch
                out_alpha[R, c] = float(min(1.0, w[r, c]))
            else:
                dim_ch[R, c] = ch
                cr, cg, cb = _hsv(DIM_HUE, DIM_SAT, min(CEIL, float(v[r, c])))
                rgb[R, c, 0], rgb[R, c, 1], rgb[R, c, 2] = cr, cg, cb

    S['stats'] = {'lit': int(lit_mask.sum()),
                  'drawn': int((chars != ' ').sum()),
                  'cover': round(float(_coverage(t)), 3),
                  'gain': round(float(_section_gain(t)), 3),
                  'held': bool(_held(t))}

    op(DIM_DAT).text = '\n'.join(''.join(row) for row in dim_ch)
    op(LIT_DAT).text = '\n'.join(''.join(row) for row in lit_ch)

    out = np.empty((VROWS, COLS, 4), np.float32)
    out[:, :, 0:3] = rgb
    out[:, :, 3] = out_alpha
    scriptOp.copyNumpyArray(np.ascontiguousarray(np.flipud(out)))
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS       # no input; must run every frame
