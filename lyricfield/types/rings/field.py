"""Rings, inside TouchDesigner: the beat as circles from the centre.

The first renderer here whose Script TOP *is* the picture. The grid types run
it at one pixel per cell and let Text TOPs draw glyphs; this one runs it at the
frame's own resolution and writes pixels, so there is no lattice anywhere in it.

  * a kick is born as a ring and expands until it leaves the frame,
  * a snare throws spokes out from the centre,
  * the hi-hats are a fine grain turning slowly around it.

Everything is whole-array. At 720x1280 a per-pixel Python loop would be about a
million iterations a frame; the same work as numpy broadcasts is a handful of
milliseconds, and every expression below is written that way deliberately.
"""

PARAMS_DAT = 'params'

DEFAULTS = {
    'width': 720, 'height': 1280, 'scale': 0.5,
    'speed': 0.62, 'thick': 0.035, 'birth': 0.75, 'decay': 1.1,
    'seed': 0.04, 'limit': 14,
    'count': 12, 'peak': 0.45, 'fade': 0.28, 'taper': 2.2,
    'lift': 0.14, 'settle': 0.22, 'spin': 0.35, 'freq': 34.0,
    'hue': 0.54, 'sat': 0.45, 'core': 0.22, 'floor': 0.015,
    'intro_open': 0.30, 'arrive': 0.80, 'outro': 12.0,
    # measured facts, pushed with the params
    'kick_in': 0.0, 'high_in': 0.0, 'duration': 0.0,
}

PARAMS_MISSING = False

S = {}

INTRO_RAMP = 2.0


def _load_params():
    # Through the prelude's reader, which accepts both the module form `sync`
    # writes and the JSON form a preview capture writes. Reading only JSON
    # meant this renderer ran every real render on the fallbacks below.
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
    g['LIMIT'] = int(g['LIMIT'])
    g['COUNT'] = int(g['COUNT'])
    dur = float(g['DURATION'] or 0.0)
    if dur <= 0.0:
        try:
            dur = float(root.time.end) / float(root.time.rate)
        except Exception:
            dur = 0.0
    g['TAIL_END'] = dur
    S.clear()                    # the radius grid is sized from these
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
    """Where in the piece this is, as a multiplier on the whole field."""
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


def _grids():
    """Radius and angle for every pixel, computed once.

    This is the whole reason a pixel renderer is affordable here: the two
    expensive arrays never change, so the per-frame cost is a handful of
    broadcasts over them rather than any trigonometry at all.
    """
    import numpy as np

    if 'r' in S:
        return S['r'], S['a']
    h = max(8, int(HEIGHT * SCALE))
    w = max(8, int(WIDTH * SCALE))
    # Normalised so that 1.0 is half the frame's HEIGHT, which is what makes
    # `speed` and `thick` mean the same thing whatever the aspect ratio.
    ys = (np.arange(h, dtype=np.float32) - (h - 1) * 0.5) / (h * 0.5)
    xs = (np.arange(w, dtype=np.float32) - (w - 1) * 0.5) / (h * 0.5)
    yy = ys[:, None]
    xx = xs[None, :]
    S['r'] = np.sqrt(xx * xx + yy * yy).astype(np.float32)
    S['a'] = np.arctan2(yy, xx).astype(np.float32)
    S['shape'] = (h, w)
    return S['r'], S['a']


def _rings(t):
    """Every live ring, as one array over the field."""
    import numpy as np

    r, _ = _grids()
    out = np.zeros(S['shape'], np.float32)
    live = []
    for born in S.get('rings', ()):
        age = t - born
        if age < 0.0 or age > DECAY:
            continue
        live.append(born)
        # Born at `seed` rather than at zero: a ring of zero radius is a dot at
        # the centre, which reads as a flash rather than as something leaving.
        rad = SEED + SPEED * age
        fade = min(1.0, max(0.0, 1.0 - age / max(1e-6, DECAY)))
        d = (r - rad) / max(1e-6, THICK)
        out += (BIRTH * fade) * np.exp(-0.5 * d * d)
    S['rings'] = live[-LIMIT:]
    return out


def _spokes(t):
    """The snare, as arms from the centre."""
    import numpy as np

    r, a = _grids()
    since = t - S.get('snare_t', -1.0e9)
    # Clamped at BOTH ends. `since` goes negative whenever a strike sits
    # ahead of `t` -- which a seek makes routine -- and an envelope of
    # `1 - since/decay` is then greater than one and grows without limit.
    # Measured: it drove the field's mean to 0.86 of white, a flat glare
    # with the rings invisible inside it.
    env = min(1.0, max(0.0, 1.0 - since / max(1e-6, FADE)))
    if env <= 0.0:
        return np.zeros(S['shape'], np.float32)
    # `cos(count * angle)` raised to a power gives `count` arms with soft
    # edges, and the taper thins them as they go out.
    arms = np.cos(COUNT * (a + S.get('snare_phase', 0.0)))
    arms = np.maximum(0.0, arms) ** 3.0
    return (PEAK * env) * arms * np.exp(-TAPER * r)


def _grain(t):
    """The hi-hats: a fine texture turning around the centre."""
    import numpy as np

    r, a = _grids()
    since = t - S.get('high_t', -1.0e9)
    env = min(1.0, max(0.0, 1.0 - since / max(1e-6, SETTLE)))
    if env <= 0.0 or LIFT <= 0.0:
        return np.zeros(S['shape'], np.float32)
    turn = 2.0 * 3.14159265 * SPIN * t
    g = 0.5 + 0.5 * np.sin(FREQ * a + turn)
    return (LIFT * env) * g * np.clip(1.0 - r * 0.5, 0.0, 1.0)


def _hsv(h, s, v):
    """HSV to RGB, linear in v so the whole field is one broadcast multiply."""
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

    r, _ = _grids()

    if 'drums' not in S:
        S['drums'] = _read_drums()
    since = S.get('t_prev', t)
    S['t_prev'] = t
    if _struck(S['drums']['kick'], t, since):
        S.setdefault('rings', []).append(t)
    if _struck(S['drums']['snare'], t, since):
        S['snare_t'] = t
        # Turn the arms a little each time, so a run of snares does not stamp
        # the identical shape over and over.
        S['snare_phase'] = S.get('snare_phase', 0.0) + 0.37
    if _struck(S['drums']['hat'], t, since):
        S['high_t'] = t

    # The centre glows, always: it is where everything is born, and a field of
    # rings with no source reads as wallpaper.
    field = FLOOR + CORE * np.exp(-3.0 * r * r)
    field = field + _rings(t) + _spokes(t) + _grain(t)
    field *= _section_gain(t)
    field = np.clip(field, 0.0, 1.0)

    cr, cg, cb = _hsv(HUE, SAT, 1.0)
    h, w = S['shape']
    out = np.empty((h, w, 4), np.float32)
    out[:, :, 0] = field * cr
    out[:, :, 1] = field * cg
    out[:, :, 2] = field * cb
    out[:, :, 3] = 1.0
    scriptOp.copyNumpyArray(np.ascontiguousarray(np.flipud(out)))

    S['stats'] = {'rings': len(S.get('rings', ())),
                  'peak': round(float(field.max()), 4),
                  'mean': round(float(field.mean()), 5),
                  'params_missing': PARAMS_MISSING}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS       # no input; must run every frame
