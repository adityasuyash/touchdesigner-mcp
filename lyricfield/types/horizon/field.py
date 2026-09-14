"""Horizon, inside TouchDesigner: a neon grid running to a banded sun.

The only renderer here that draws a *place*. Everything else is a pattern over
black; this has a floor in perspective, a horizon, and a sun sitting on it, and
the lyrics stand in that scene rather than floating in front of nothing.

The floor is real perspective, not a skewed grid: for every pixel below the
horizon the depth is `1 / (horizon - y)`, which is what a plane under a camera
actually gives you. Lanes are lines of constant screen-x scaled by that depth;
rungs are lines of constant depth, moving toward the viewer.

All whole-array, like every renderer written in this pass.
"""

CUE_DAT = 'lyrics'
LINE_DAT = 'line'
TEXT_TOP = 'hz_text'
PARAMS_DAT = 'params'

DEFAULTS = {
    'width': 720, 'height': 1280, 'scale': 0.6,
    'horizon': 0.52, 'lanes': 16.0, 'rungs': 13.0, 'speed': 0.55,
    'weight': 0.055, 'lift': 0.9, 'haze': 2.1,
    'radius': 0.3, 'size': 88.0, 'rise': 0.16, 'bands': 9.0, 'duck': 0.55, 'glowr': 0.85,
    'lead': 0.3, 'hold': 0.8, 'fade': 0.4, 'line_y': 0.3, 'wrap': 14,
    'hot': 0.92, 'cold': 0.52, 'sat': 0.85, 'sky': 0.30, 'floor': 0.02,
    'kick_lift': 0.35, 'kick_time': 0.28,
    'intro_open': 0.4, 'arrive': 0.88, 'outro': 12.0,
    'kick_in': 0.0, 'high_in': 0.0, 'duration': 0.0, 'offset': 0.0,
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
    for k in ('WIDTH', 'HEIGHT', 'WRAP'):
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


def _grids():
    """Screen x and y in 0..1, built once. y is 0 at the top."""
    import numpy as np

    if 'x' in S:
        return S['x'], S['y']
    h = max(8, int(HEIGHT * SCALE))
    w = max(8, int(WIDTH * SCALE))
    S['y'] = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    S['x'] = np.linspace(0.0, 1.0, w, dtype=np.float32)[None, :]
    S['shape'] = (h, w)
    return S['x'], S['y']


def _lines(v, weight):
    """How close each value is to a whole number, as a hard-ish line.

    `1 - smoothstep` over the distance to the nearest integer: a line of
    constant width in the space `v` is measured in, which for the floor means
    the lanes converge and the rungs bunch up exactly as perspective requires.
    """
    import numpy as np

    d = np.abs(v - np.round(v))
    a = np.clip(1.0 - d / max(1e-6, weight), 0.0, 1.0)
    return a * a * (3.0 - 2.0 * a)


def _scene(t, kick_env):
    """Sky, sun and floor, as one brightness field plus a hue field."""
    import numpy as np

    x, y = _grids()
    h, w = S['shape']

    below = y > HORIZON
    # ---- the floor ------------------------------------------------------
    # Depth of the plane under the camera. Guarded away from the horizon,
    # where it goes to infinity and the grid would alias into noise.
    denom = np.maximum(y - HORIZON, 1e-3)
    depth = 0.12 / denom
    lane = (x - 0.5) * depth * LANES
    rung = depth * RUNGS - SPEED * RUNGS * t
    grid = np.maximum(_lines(lane, WEIGHT * 2.0), _lines(rung, WEIGHT))
    # Fade the floor out toward the horizon, or the converging lines turn into
    # a solid bar of light exactly where the eye goes.
    grid = grid * np.exp(-HAZE * depth * 0.06)
    floor_v = np.where(below, grid * (LIFT + KICK_LIFT * kick_env), 0.0)

    # ---- the sky --------------------------------------------------------
    # Darkest at the top, brightest at the horizon.
    up = np.clip((HORIZON - y) / max(1e-6, HORIZON), 0.0, 1.0)
    sky_v = np.where(below, 0.0, SKY * (1.0 - up) ** 1.6)

    # ---- the sun --------------------------------------------------------
    cy = HORIZON - RISE
    # HEIGHT/WIDTH, not the other way up. In 0..1 coordinates a step in y
    # covers `height` pixels and a step in x covers `width`, so y is the axis
    # that must be scaled up to make a circle. Inverted, the sun came out as a
    # tall ellipse running the whole height of the frame.
    ar = (HEIGHT / float(WIDTH))
    dx = (x - 0.5)
    dy = (y - cy) * ar
    rr = np.sqrt(dx * dx + dy * dy) / max(1e-6, RADIUS)
    # And it sits ON the horizon: below that line is floor, and a sun painted
    # over the floor is not a horizon, it is a shape in front of one.
    disc = (rr <= 1.0) & (y <= HORIZON)
    # Slices cut out of the lower half, widening downward.
    band_phase = (y - cy) * BANDS * 6.0
    cut = (band_phase % 1.0) < DUCK
    lower = y > cy
    sun_v = np.where(disc & ~(lower & cut),
                     GLOWR * np.clip(1.0 - (y - (cy - RADIUS)) * 1.1, 0.15, 1.0),
                     0.0)

    v = FLOOR + sky_v + sun_v + floor_v
    # Hue: the floor and the sun take the cold and hot ends, the sky runs
    # between them. This is the collision the whole look is built on.
    hue = np.where(below, COLD, HOT - (HOT - COLD) * up * 0.35)
    hue = np.where(disc, HOT, hue)
    return np.clip(v, 0.0, 1.6), hue


def _read_lines():
    rows = []
    try:
        d = op(CUE_DAT)
    except Exception:
        return rows
    if d is None:
        return rows
    try:
        n = d.numRows
    except Exception:
        return rows
    by_line, order = {}, []
    for r in range(n):
        try:
            word = d[r, 0].val.strip()
            start = float(d[r, 1].val.strip())
            line = int(float(d[r, 2].val.strip())) if d.numCols > 2 else 0
        except (ValueError, IndexError, AttributeError):
            continue
        if not word:
            continue
        if line not in by_line:
            by_line[line] = []
            order.append(line)
        by_line[line].append((start, word))
    for line in order:
        ws = sorted(by_line[line])
        rows.append((ws[0][0], ws[-1][0], ' '.join(x for _, x in ws)))
    rows.sort()
    return rows


def _wrap(text, width):
    out, cur = [], ''
    for word in text.split():
        if not cur:
            cur = word
        elif len(cur) + 1 + len(word) <= width:
            cur = cur + ' ' + word
        else:
            out.append(cur)
            cur = word
    if cur:
        out.append(cur)
    return '\n'.join(out)


def _line_at(lines, t):
    best, lit = '', 0.0
    for first, last, text in lines:
        a, b = first - LEAD, last + HOLD
        if t < a or t > b + FADE:
            continue
        if t <= b:
            best, lit = text, 1.0
        else:
            v = max(0.0, 1.0 - (t - b) / max(1e-6, FADE))
            if v > lit:
                best, lit = text, v
    return best, lit


def _hsv_arrays(hue, sat, val):
    """Per-pixel HSV to RGB, vectorised.

    The scene has two hues in one frame, so the scalar version every other
    renderer uses cannot serve here.
    """
    import numpy as np

    h = (hue % 1.0) * 6.0
    i = np.floor(h).astype(np.int32)
    f = h - i
    p = np.zeros_like(h)
    q = 1.0 - f
    tt = f
    one = np.ones_like(h)
    r = np.select([i == 0, i == 1, i == 2, i == 3, i == 4],
                  [one, q, p, p, tt], default=one)
    g = np.select([i == 0, i == 1, i == 2, i == 3, i == 4],
                  [tt, one, one, q, p], default=p)
    b = np.select([i == 0, i == 1, i == 2, i == 3, i == 4],
                  [p, p, tt, one, one], default=q)
    r = (1.0 - sat) + sat * r
    g = (1.0 - sat) + sat * g
    b = (1.0 - sat) + sat * b
    return val * r, val * g, val * b


def _setpar(path, name, value):
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
        stamp = (op(CUE_DAT).numRows if op(CUE_DAT) is not None else 0,
                 len(op(PARAMS_DAT).text) if op(PARAMS_DAT) is not None else 0)
    except Exception:
        stamp = (0, 0)
    if S.get('stamp') != stamp:
        _apply_params()
        S['stamp'] = stamp
        S['lines'] = _read_lines()

    if 'drums' not in S:
        S['drums'] = _read_drums()
    since = S.get('t_prev', t)
    S['t_prev'] = t
    if _struck(S['drums']['kick'], t, since):
        S['kick_t'] = t
    kick_env = min(1.0, max(0.0,
        1.0 - (t - S.get('kick_t', -1.0e9)) / max(1e-6, KICK_TIME)))

    text, _lit = _line_at(S.get('lines') or [], t)
    try:
        op(LINE_DAT).text = _wrap(text, WRAP) if text else ''
    except Exception:
        pass
    _setpar(TEXT_TOP, 'fontsizex', SIZE)
    _setpar(TEXT_TOP, 'fontsizey', SIZE)
    _setpar(TEXT_TOP, 'positiony', (0.5 - LINE_Y) * HEIGHT)

    v, hue = _scene(t, kick_env)
    v = np.clip(v * _section_gain(t), 0.0, 1.0)
    r, g, b = _hsv_arrays(hue, SAT, v)

    h, w = S['shape']
    out = np.empty((h, w, 4), np.float32)
    out[:, :, 0] = r
    out[:, :, 1] = g
    out[:, :, 2] = b
    out[:, :, 3] = 1.0
    scriptOp.copyNumpyArray(np.ascontiguousarray(np.flipud(out)))

    S['stats'] = {'line': text, 'mean': round(float(v.mean()), 5),
                  'peak': round(float(v.max()), 4),
                  'params_missing': PARAMS_MISSING}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS
