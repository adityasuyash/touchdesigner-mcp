"""The beat response, inside TouchDesigner.

Pushed into a Script TOP the way every renderer's `field.py` is, and it is the
`monument` pattern exactly: the TOP is not the picture. It is sixteen pixels
that nothing looks at, and its job is to read the drum table each frame and set
the parameters of the operators around it.

What it drives:

    fx_shake   transformTOP   tx, ty        the jolt
    fx_zoom    transformTOP   sx, sy        the punch
    fx_split   reorderTOP     (via fx_r/fx_b transforms) the fringe
    fx_bloom   blurTOP        size          the swell
    fx_level   levelTOP       brightness1   the lift that rides with it

Nothing here knows which renderer drew the frame it is moving, which is the
whole point: one chain, every word look.

Every envelope is `impulse` from `lyricfield/beat.py` -- a fast eased attack and
a damped spring that crosses rest and settles -- rather than `1 - age/decay`,
which is what makes a beat effect read as a meter. The same file is imported by
the tests, so the shape asserted there is the shape that runs.
"""

# `fx_params`, not `params`: the renderer's own params DAT is called `params`
# and lives in the words container, and this chain sits at the root beside it.
# Reading the wrong name does not fail -- it falls back to the DEFAULTS below
# and every preset renders as the same picture, which is exactly what happened:
# five previews recorded, `jolt` and `pulse` identical to three decimal places.
PARAMS_DAT = 'fx_params'

DEFAULTS = {
    'width': 720, 'height': 1280,
    'zoom_on': True, 'zoom_drive': 'kick', 'zoom_amount': 1.075,
    'zoom_decay': 0.42, 'zoom_float_': 0.25,
    'bloom_on': True, 'bloom_drive': 'kick', 'bloom_amount': 14.0,
    'bloom_decay': 0.55, 'bloom_lift': 0.22,
    'shake_on': False, 'shake_drive': 'snare', 'shake_amount': 0.012,
    'shake_decay': 0.24, 'shake_tilt': 0.45,
    'split_on': False, 'split_drive': 'snare', 'split_amount': 0.006,
    'split_decay': 0.20,
    'offset': 0.0,
}

PARAMS_MISSING = False

S = {}

# Seconds of attack, and the spring's cycles-per-release. Mirrors
# `lyricfield/beat.py`; a test asserts the two agree, because a drift between
# them would mean the preview and the render disagree about the feel.
ATTACK = 0.04
BOUNCE = 0.62


def _load_params():
    global PARAMS_MISSING
    p, PARAMS_MISSING = _read_params(PARAMS_DAT)
    return p


def _apply_params():
    P = _load_params()
    g = globals()
    for key, fallback in DEFAULTS.items():
        g[key.upper()] = P.get(key, fallback)
    g['WIDTH'] = int(g['WIDTH'])
    g['HEIGHT'] = int(g['HEIGHT'])
    for k in ('ZOOM_ON', 'BLOOM_ON', 'SHAKE_ON', 'SPLIT_ON'):
        g[k] = bool(g[k])
    S.clear()
    return P


try:
    _apply_params()
except Exception:
    for _k, _v in DEFAULTS.items():
        globals()[_k.upper()] = _v


def _ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def _impulse(t, struck, decay, bounce=BOUNCE):
    """See `lyricfield/beat.py:impulse`. Kept in step by a test.

    Clamped at BOTH ends -- a strike ahead of the playhead makes the age
    negative, which a seek makes routine.
    """
    import math

    age = t - struck
    decay = max(1e-6, float(decay))
    if age < 0.0 or age > decay:
        return 0.0
    if age < ATTACK:
        return _ease(age / ATTACK)
    x = (age - ATTACK) / max(1e-6, decay - ATTACK)
    return ((1.0 - x) ** 1.8) * math.cos(math.pi * 2.0 * max(0.0, bounce) * x)


def _drift(t, seed=0.0):
    """A slow wander in -1..1 that never repeats on a useful timescale.

    What keeps the layer moving between hits. Without it every strike reads as
    a stutter out of a freeze, which is the difference between floaty and
    mechanical.
    """
    import math

    # Periods of about 5.6, 8.8 and 17 seconds. The first draft ran at 20-70s,
    # which over a four-second preview is a one-way ramp rather than a wander --
    # slow enough to be invisible is the same as not being there. The phase
    # offsets stop all three starting at zero together, which would make the
    # first second of every render a ramp from nothing.
    a = math.sin(t * 1.1300 + 0.7 + seed * 1.7)
    b = math.sin(t * 0.7130 + 2.3 + seed * 3.1)
    c = math.sin(t * 0.3670 + 4.1 + seed * 5.9)
    return (a + b + c) / 3.0


def _shake_offset(t, env, span, tilt, seed=1.0):
    """See `lyricfield/beat.py:shake_offset`. Kept in step by a test.

    Direction and magnitude are separate. The first version multiplied the
    amplitude by the drift itself, whose mean absolute value is 0.39, so a jolt
    asking for 32 pixels landed as 6 and Jolt read as a dimmer Punch.
    """
    import math

    dx, dy = _drift(t, seed), _drift(t, seed + 1.0)
    n = math.hypot(dx, dy)
    if n < 1e-9:
        dx, dy, n = 1.0, 0.0, 1.0
    # Tilt shapes the direction; it must not shrink the throw. Weighting the
    # axes and stopping there costs about half the amplitude at tilt 0.45, so
    # the vector is renormalised and `amount` is the peak displacement it says
    # it is rather than some fraction of it.
    wx, wy = (dx / n) * (1.0 - tilt), (dy / n) * tilt
    m = math.hypot(wx, wy)
    if m < 1e-9:
        wx, wy, m = (1.0, 0.0, 1.0) if tilt < 0.5 else (0.0, 1.0, 1.0)
    reach = span * env
    return (reach * wx / m, reach * wy / m)


def _last(kind, t):
    """When the most recent `kind` landed at or before `t`.

    A lookup rather than edge detection: an effect needs to know how far
    through a response it is, not whether one just started, and an edge that
    fires once cannot answer that after a seek.
    """
    times = S.get('drums', {}).get(kind) or ()
    if not times:
        return -1.0e9
    lo, hi = 0, len(times)
    while lo < hi:
        mid = (lo + hi) // 2
        if times[mid] <= t:
            lo = mid + 1
        else:
            hi = mid
    return times[lo - 1] if lo else -1.0e9


def _setpar(path, name, value):
    """Set a parameter on a sibling, quietly.

    A missing operator costs the picture its motion, not its existence, and
    raising here would stop the cook.
    """
    try:
        o = op(path)
        if o is None:
            return
        p = getattr(o.par, name, None)
        if p is not None:
            p.val = value
    except Exception:
        pass


def onSetupParameters(scriptOp):
    """No custom parameters; see monument for why none rather than one."""
    return


def onPulse(par):
    return


def onCook(scriptOp):
    import numpy as np

    t = float(me.time.seconds) + float(OFFSET or 0.0)

    try:
        stamp = len(op(PARAMS_DAT).text) if op(PARAMS_DAT) is not None else 0
    except Exception:
        stamp = 0
    if S.get('stamp') != stamp:
        _apply_params()
        S['stamp'] = stamp

    if 'drums' not in S:
        S['drums'] = _read_drums()

    # ---- zoom: the punch ---------------------------------------------------
    if ZOOM_ON:
        env = _impulse(t, _last(ZOOM_DRIVE, t), ZOOM_DECAY)
        travel = float(ZOOM_AMOUNT) - 1.0
        # The breath under it, so a held frame is never perfectly still.
        breathe = travel * float(ZOOM_FLOAT_) * 0.5 * _drift(t, 0.0)
        scale = 1.0 + travel * env + breathe
        _setpar('fx_zoom', 'sx', scale)
        _setpar('fx_zoom', 'sy', scale)
    else:
        _setpar('fx_zoom', 'sx', 1.0)
        _setpar('fx_zoom', 'sy', 1.0)

    # ---- shake: the jolt ---------------------------------------------------
    if SHAKE_ON:
        env = _impulse(t, _last(SHAKE_DRIVE, t), SHAKE_DECAY)
        span = float(SHAKE_AMOUNT) * min(WIDTH, HEIGHT)
        tx, ty = _shake_offset(t, env, span, float(SHAKE_TILT))
        _setpar('fx_shake', 'tx', tx)
        _setpar('fx_shake', 'ty', ty)
    else:
        _setpar('fx_shake', 'tx', 0.0)
        _setpar('fx_shake', 'ty', 0.0)

    # ---- split: the fringe -------------------------------------------------
    if SPLIT_ON:
        env = _impulse(t, _last(SPLIT_DRIVE, t), SPLIT_DECAY)
        gap = float(SPLIT_AMOUNT) * WIDTH * env
        _setpar('fx_r', 'tx', gap)
        _setpar('fx_b', 'tx', -gap)
    else:
        _setpar('fx_r', 'tx', 0.0)
        _setpar('fx_b', 'tx', 0.0)

    # ---- bloom: the swell --------------------------------------------------
    if BLOOM_ON:
        env = _impulse(t, _last(BLOOM_DRIVE, t), BLOOM_DECAY)
        # Only the positive half lifts the glow: a blur radius below rest would
        # mean sharpening, which a Blur TOP cannot do and would clamp anyway.
        up = max(0.0, env)
        _setpar('fx_bloom', 'size', float(BLOOM_AMOUNT) * up)
        _setpar('fx_level', 'brightness1', 1.0 + float(BLOOM_LIFT) * up)
    else:
        _setpar('fx_bloom', 'size', 0.0)
        _setpar('fx_level', 'brightness1', 1.0)

    out = np.zeros((16, 16, 4), np.float32)
    out[:, :, 3] = 1.0
    scriptOp.copyNumpyArray(np.ascontiguousarray(out))

    S['stats'] = {'params_missing': PARAMS_MISSING,
                  'on': [n for n, v in (('zoom', ZOOM_ON), ('bloom', BLOOM_ON),
                                        ('shake', SHAKE_ON), ('split', SPLIT_ON))
                         if v],
                  'drums': {k: len(v) for k, v in (S.get('drums') or {}).items()}}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS       # no input; must run every frame
