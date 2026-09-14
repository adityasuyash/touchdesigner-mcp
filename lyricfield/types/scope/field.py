"""Scope, inside TouchDesigner: one continuous curve, glowing.

A Lissajous figure -- two sines at a ratio, one per axis -- drawn as a bright
point travelling the curve with its recent past still glowing behind it. On
black, with nothing else in the frame, it reads as an instrument rather than as
a picture, which is what makes it worth having beside `rings` and `strata`.

The trail is drawn from the curve's own past, not accumulated in a buffer. That
is the difference between a renderer that re-renders identically and one that
depends on how it got here: a frame is a pure function of its own timestamp, so
seeking to the middle of a song gives exactly the frame a full playthrough
would.

Points are splatted with `np.add.at`, which is one vectorised scatter over a
few hundred samples rather than any per-pixel work at all.
"""

PARAMS_DAT = 'params'

DEFAULTS = {
    'width': 720, 'height': 1280, 'scale': 0.6,
    'freqx': 3.0, 'freqy': 2.0, 'slip': 0.05, 'size': 0.38, 'rate': 0.9,
    'seconds': 0.55, 'samples': 1400, 'weight': 0.9, 'taper': 2.6,
    'hue': 0.33, 'sat': 0.7, 'floor': 0.012,
    'kick_bend': 0.35, 'kick_time': 0.45, 'hat_lift': 0.25, 'hat_time': 0.12,
    'intro_open': 0.3, 'arrive': 0.85, 'outro': 12.0,
    'kick_in': 0.0, 'high_in': 0.0, 'duration': 0.0,
}

PARAMS_MISSING = False

S = {}

INTRO_RAMP = 2.0
TAU = 6.283185307179586


def _load_params():
    global PARAMS_MISSING
    PARAMS_MISSING = False
    try:
        d = op(PARAMS_DAT)
        txt = d.text if d is not None else ''
    except Exception:
        txt = ''
    if not txt.strip():
        PARAMS_MISSING = True
        return {}
    try:
        import json
        out = json.loads(txt)
    except Exception:
        PARAMS_MISSING = True
        return {}
    return out if isinstance(out, dict) else {}


def _apply_params():
    P = _load_params()
    g = globals()
    for key, fallback in DEFAULTS.items():
        g[key.upper()] = P.get(key, fallback)
    for k in ('WIDTH', 'HEIGHT', 'SAMPLES'):
        g[k] = int(g[k])
    dur = float(g['DURATION'] or 0.0)
    if dur <= 0.0:
        try:
            dur = float(root.time.end) / float(root.time.rate)
        except Exception:
            dur = 0.0
    g['TAIL_END'] = dur
    S.clear()
    return P


try:
    _apply_params()
except Exception:
    for _k, _v in DEFAULTS.items():
        globals()[_k.upper()] = _v
    globals()['TAIL_END'] = 0.0


def _smooth(a):
    a = max(0.0, min(1.0, a))
    return a * a * (3.0 - 2.0 * a)


def _section_gain(t):
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


def _shape():
    if 'shape' not in S:
        S['shape'] = (max(8, int(HEIGHT * SCALE)), max(8, int(WIDTH * SCALE)))
    return S['shape']


def _curve(ts, bend):
    """Where the point is at each time in `ts`, in 0..1 frame space.

    Aspect-corrected against the smaller side, so the figure is the same shape
    whatever the frame is -- the mistake that made a circle an oval twice
    already in this pass.
    """
    import numpy as np

    side = float(min(WIDTH, HEIGHT))
    kx, ky = side / float(WIDTH), side / float(HEIGHT)
    ph = TAU * SLIP * ts
    fx = FREQX
    fy = FREQY + bend
    x = 0.5 + SIZE * kx * np.sin(TAU * fx * RATE * ts + ph)
    y = 0.5 + SIZE * ky * np.sin(TAU * fy * RATE * ts)
    return x, y


def _draw(t, bend, gain):
    """The curve's recent past, splatted into the field."""
    import numpy as np

    h, w = _shape()
    out = np.zeros((h, w), np.float32)
    # Sample backward from now. `age` 0 is the live point, 1 the oldest.
    age = np.linspace(0.0, 1.0, SAMPLES, dtype=np.float32)
    ts = t - age * SECONDS
    x, y = _curve(ts, bend)
    bright = WEIGHT * np.exp(-TAPER * age) * gain

    xi = np.clip((x * (w - 1)).astype(np.int32), 0, w - 1)
    yi = np.clip((y * (h - 1)).astype(np.int32), 0, h - 1)
    # One scatter, not a loop: `add.at` accumulates where samples land on the
    # same pixel, which is what makes the slow parts of the figure brighter --
    # exactly what a phosphor screen does.
    np.add.at(out, (yi, xi), bright)
    return out


def _hsv(h, s, v):
    h = (h % 1.0) * 6.0
    i = int(h)
    f = h - i
    p, q, tt = 0.0, 1.0 - f, f
    if i == 0:
        r, g, b = 1.0, tt, p
    elif i == 1:
        r, g, b = q, 1.0, p
    elif i == 2:
        r, g, b = p, 1.0, tt
    elif i == 3:
        r, g, b = p, q, 1.0
    elif i == 4:
        r, g, b = tt, p, 1.0
    else:
        r, g, b = 1.0, p, q
    r = (1.0 - s) + s * r
    g = (1.0 - s) + s * g
    b = (1.0 - s) + s * b
    return v * r, v * g, v * b


def onSetupParameters(scriptOp):
    """No custom parameters; see monument for why none rather than one."""
    return


def onPulse(par):
    return


def onCook(scriptOp):
    import numpy as np

    t = float(me.time.seconds)

    try:
        stamp = len(op(PARAMS_DAT).text) if op(PARAMS_DAT) is not None else 0
    except Exception:
        stamp = 0
    if S.get('stamp') != stamp:
        _apply_params()
        S['stamp'] = stamp

    if 'drums' not in S:
        S['drums'] = _read_drums()
    since = S.get('t_prev', t)
    S['t_prev'] = t
    if _struck(S['drums']['kick'], t, since):
        S['kick_t'] = t
    if _struck(S['drums']['hat'], t, since):
        S['hat_t'] = t
    kick_env = min(1.0, max(0.0,
        1.0 - (t - S.get('kick_t', -1.0e9)) / max(1e-6, KICK_TIME)))
    hat_env = min(1.0, max(0.0,
        1.0 - (t - S.get('hat_t', -1.0e9)) / max(1e-6, HAT_TIME)))

    gain = _section_gain(t) * (1.0 + HAT_LIFT * hat_env)
    field = _draw(t, KICK_BEND * kick_env, gain)
    field = np.clip(FLOOR + field, 0.0, 1.0)

    cr, cg, cb = _hsv(HUE, SAT, 1.0)
    h, w = _shape()
    out = np.empty((h, w, 4), np.float32)
    out[:, :, 0] = field * cr
    out[:, :, 1] = field * cg
    out[:, :, 2] = field * cb
    out[:, :, 3] = 1.0
    scriptOp.copyNumpyArray(np.ascontiguousarray(np.flipud(out)))

    S['stats'] = {'mean': round(float(field.mean()), 6),
                  'peak': round(float(field.max()), 4),
                  'bend': round(KICK_BEND * kick_env, 4),
                  'params_missing': PARAMS_MISSING}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS
