"""Halftone, inside TouchDesigner: the beat as a dot screen.

Tone is carried by the AREA of a dot, not by its brightness. That is the whole
idea of a halftone and it is the one thing easy to get wrong: a lattice of dots
whose *brightness* follows the music is just a grid that flickers. Here the dot
radius goes as the square root of the tone, so area is linear in it, and the
picture reads the way print does.

Three screens, one per channel, each rotated a little from the last. The beating
between them is the rosette -- the thing that makes a halftone recognisable at a
glance rather than merely dotty.

Everything is whole-array. Three rotations and three lattice evaluations over
the reduced field are a few milliseconds; the same work per pixel in Python
would be several million iterations a frame.
"""

PARAMS_DAT = 'params'

DEFAULTS = {
    'width': 720, 'height': 1280, 'scale': 0.5,
    'pitch': 36.0, 'angle': 45.0, 'dot': 0.62, 'soft': 0.13,
    'base': 0.10,
    'kick_lift': 0.55, 'kick_time': 0.30,
    'snare_lift': 0.30, 'snare_time': 0.22,
    'hat_lift': 0.12, 'hat_time': 0.14,
    'wave': 0.18, 'wave_beats': 8.0, 'vignette': 0.55,
    'hue': 0.08, 'sat': 0.35, 'separate': True, 'spread': 30.0,
    'intro_open': 0.30, 'arrive': 0.82, 'outro': 10.0,
    # measured facts, pushed with the params
    'kick_in': 0.0, 'high_in': 0.0, 'duration': 0.0, 'beat_period': 0.4615,
}

PARAMS_MISSING = False

S = {}

INTRO_RAMP = 2.0


def _load_params():
    # Through the prelude's reader, which accepts both the module form `sync`
    # writes and the JSON form a preview capture writes.
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
    g['SEPARATE'] = bool(g['SEPARATE'])
    dur = float(g['DURATION'] or 0.0)
    if dur <= 0.0:
        try:
            dur = float(root.time.end) / float(root.time.rate)
        except Exception:
            dur = 0.0
    g['TAIL_END'] = dur
    S.clear()                    # the coordinate grids are sized from these
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
    """Where in the piece this is, as a multiplier on the tone."""
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
    """Normalised coordinates for every pixel, computed once.

    Normalised against the frame's HEIGHT on both axes, so a dot is round and
    the pitch means the same thing whatever the aspect ratio. Getting this
    backwards is what turned a sun into a wedge and a circle into an oval
    earlier in this project.
    """
    import numpy as np

    if 'x' in S:
        return S['x'], S['y']
    h = max(8, int(HEIGHT * SCALE))
    w = max(8, int(WIDTH * SCALE))
    ys = (np.arange(h, dtype=np.float32) - (h - 1) * 0.5) / (h * 0.5)
    xs = (np.arange(w, dtype=np.float32) - (w - 1) * 0.5) / (h * 0.5)
    S['x'] = xs[None, :]
    S['y'] = ys[:, None]
    S['shape'] = (h, w)
    return S['x'], S['y']


def _env(t, struck, decay):
    """A strike's decay, clamped at BOTH ends.

    Negative `t - struck` happens whenever a hit sits ahead of the playhead,
    which a seek makes routine, and an unclamped `1 - age/decay` is then greater
    than one and grows without limit. It drove another renderer's whole field to
    a flat glare before it was caught.
    """
    return min(1.0, max(0.0, 1.0 - (t - struck) / max(1e-6, decay)))


def _tone(t):
    """The picture the dots are a screen of: one array, 0..1."""
    import numpy as np

    x, y = _grids()
    r2 = x * x + y * y

    v = np.full(S['shape'], float(BASE), np.float32)

    # A kick swells the middle outward.
    k = _env(t, S.get('kick_t', -1.0e9), KICK_TIME)
    if k > 0.0 and KICK_LIFT > 0.0:
        v = v + (KICK_LIFT * k) * np.exp(-2.2 * r2).astype(np.float32)

    # A snare throws a horizontal band that travels down as it fades.
    s = _env(t, S.get('snare_t', -1.0e9), SNARE_TIME)
    if s > 0.0 and SNARE_LIFT > 0.0:
        centre = -1.0 + 2.0 * (1.0 - s)
        band = np.exp(-18.0 * (y - centre) ** 2).astype(np.float32)
        v = v + (SNARE_LIFT * s) * band

    # Hats lift the whole sheet a little.
    hh = _env(t, S.get('hat_t', -1.0e9), HAT_TIME)
    if hh > 0.0 and HAT_LIFT > 0.0:
        v = v + HAT_LIFT * hh

    # ... and a slow diagonal swell, so a quiet stretch still moves.
    if WAVE > 0.0:
        period = max(1e-6, BEAT_PERIOD * WAVE_BEATS)
        phase = 2.0 * 3.14159265 * (t / period)
        v = v + WAVE * (0.5 + 0.5 * np.sin(1.7 * (x + y) - phase))

    if VIGNETTE > 0.0:
        v = v * (1.0 - VIGNETTE * np.clip(r2, 0.0, 1.0))
    v *= _section_gain(t)
    return np.clip(v, 0.0, 1.0)


def _screen(tone, angle_deg):
    """One separation: the tone, rendered as dots on a lattice at `angle_deg`.

    The radius goes as sqrt(tone) so that dot AREA is linear in tone. Using the
    tone as the radius directly is the obvious mistake and it makes the midtones
    far too light.
    """
    import numpy as np

    x, y = _grids()
    a = angle_deg * 3.14159265 / 180.0
    ca, sa = float(np.cos(a)), float(np.sin(a))
    # The lattice lives in rotated coordinates; `pitch` is dots across the
    # frame's width, and x spans WIDTH/HEIGHT in these units.
    span = max(1e-6, 2.0 * float(WIDTH) / float(HEIGHT))
    k = float(PITCH) / span
    u = (x * ca - y * sa) * k
    v = (x * sa + y * ca) * k

    du = u - np.round(u)
    dv = v - np.round(v)
    d = np.sqrt(du * du + dv * dv)

    r = DOT * np.sqrt(np.clip(tone, 0.0, 1.0))
    # smoothstep across the dot edge, in cell units
    e = np.clip((r - d) / max(1e-6, SOFT), 0.0, 1.0)
    return (e * e * (3.0 - 2.0 * e)).astype(np.float32)


def _hsv(h, s, v):
    """HSV to RGB, linear in v so a whole frame is one multiply."""
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

    _grids()

    if 'drums' not in S:
        S['drums'] = _read_drums()
    since = S.get('t_prev', t)
    S['t_prev'] = t
    if _struck(S['drums']['kick'], t, since):
        S['kick_t'] = t
    if _struck(S['drums']['snare'], t, since):
        S['snare_t'] = t
    if _struck(S['drums']['hat'], t, since):
        S['hat_t'] = t

    tone = _tone(t)
    h, w = S['shape']
    out = np.empty((h, w, 4), np.float32)

    if SEPARATE:
        # One screen per channel, each at its own angle. The beating between
        # them is the rosette, and it is the whole reason this reads as a
        # halftone rather than as a dot grid.
        for ch in range(3):
            out[:, :, ch] = _screen(tone, ANGLE + ch * SPREAD)
        # Tint without losing the separation: scale each channel toward the ink
        # colour rather than replacing it.
        cr, cg, cb = _hsv(HUE, SAT, 1.0)
        out[:, :, 0] *= cr
        out[:, :, 1] *= cg
        out[:, :, 2] *= cb
        peak = float(out[:, :, :3].max())
    else:
        e = _screen(tone, ANGLE)
        cr, cg, cb = _hsv(HUE, SAT, 1.0)
        out[:, :, 0] = e * cr
        out[:, :, 1] = e * cg
        out[:, :, 2] = e * cb
        peak = float(e.max())
    out[:, :, 3] = 1.0

    scriptOp.copyNumpyArray(np.ascontiguousarray(np.flipud(out)))

    S['stats'] = {'tone_mean': round(float(tone.mean()), 5),
                  'tone_peak': round(float(tone.max()), 4),
                  'peak': round(peak, 4),
                  'separate': bool(SEPARATE),
                  'params_missing': PARAMS_MISSING}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS       # no input; must run every frame
