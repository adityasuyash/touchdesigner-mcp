"""Orbit, inside TouchDesigner: each character gets its own coordinate.

This is the renderer that proves the lattice is gone. Everywhere else the glyph
positions are chosen by something structural -- a cell, a centred line, a
wrapped block -- and no parameter can escape that. Here every character is
placed individually on a parametric curve through the Text TOP's
**Specification DAT**, a table of `x`, `y`, `text` with one row per character,
so the type can be anywhere at all.

The origin of that table is LOWER-LEFT, which is measured rather than assumed:
a row at y=320 in a 400px frame drew near the top.
"""

CUE_DAT = 'lyrics'
SPEC_DAT = 'spec'
TEXT_TOP = 'orb_text'
PARAMS_DAT = 'params'

DEFAULTS = {
    'width': 720, 'height': 1280,
    'shape': 'circle', 'radius': 0.33, 'spin': 0.06, 'spread': 0.026,
    'twist': 3.0,
    'size': 46.0, 'lead': 0.3, 'hold': 0.9, 'fade': 0.4,
    'hue': 0.78, 'sat': 0.4, 'peak': 0.95, 'floor': 0.02,
    'kick_push': 0.1, 'kick_time': 0.3,
    'intro_open': 0.35, 'arrive': 0.85, 'outro': 11.0,
    'kick_in': 0.0, 'high_in': 0.0, 'duration': 0.0, 'offset': 0.0,
}

PARAMS_MISSING = False

S = {}

INTRO_RAMP = 2.0
TAU = 6.283185307179586


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


# Which paths close on themselves. A closed path can carry the line round and
# round, so its parameter wraps; an open one cannot, and wrapping it teleports
# a character from the end back to the start mid-line.
CLOSED = ('circle', 'spiral', 'lissajous')


def _point(u, scale, t=0.0):
    """Where on the curve the parameter `u` (0..1) lands, in 0..1 frame space.

    Every path is closed and centred, so `radius` means the same thing
    whichever is chosen and swapping between them never moves the line off
    frame.
    """
    import math

    a = u * TAU
    # Aspect-corrected, in both axes. A curve written in 0..1 space is an
    # ellipse on screen, because a step in x covers `width` pixels and a step
    # in y covers `height` -- the circle came out as a tall oval running off
    # the frame. The radius is taken against the SMALLER side so a circle
    # always fits, whatever the frame's shape.
    side = float(min(WIDTH, HEIGHT))
    r = RADIUS * scale
    kx, ky = side / float(WIDTH), side / float(HEIGHT)
    if SHAPE == 'spiral':
        # Winds inward as the line runs, so the first word is outermost.
        rr = r * (1.0 - 0.55 * u)
        return (0.5 + rr * kx * math.cos(a * TWIST),
                0.5 + rr * ky * math.sin(a * TWIST))
    if SHAPE == 'wave':
        # Read left to right, riding a sine that travels under the line.
        # `u` here is the character's place IN the line, not a position on a
        # loop, so the order on screen is the order it is sung in.
        # A fraction of `twist`: the same number that gives a spiral its
        # winding gives a wave three full cycles across twenty-two
        # characters, which oscillates faster than the eye can follow a
        # line of text along.
        phase = TAU * (u * max(0.3, TWIST * 0.4) - SPIN * t * 4.0)
        return 0.08 + 0.84 * u, 0.5 + r * ky * math.sin(phase)
    if SHAPE == 'lissajous':
        return (0.5 + r * kx * math.sin(a * max(1.0, TWIST)),
                0.5 + r * ky * math.sin(a * 2.0))
    return 0.5 + r * kx * math.cos(a), 0.5 + r * ky * math.sin(a)


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


def _spec(text, t, scale):
    """The Specification DAT: one row per character, each at its own point.

    Tab-separated with an `x  y  text` header, in PIXELS from the lower left.
    """
    lines = ['x\ty\ttext']
    turn = SPIN * t
    n = max(1, len(text) - 1)
    for i, ch in enumerate(text):
        if ch == ' ':
            continue
        if SHAPE in CLOSED:
            u = (i * SPREAD + turn) % 1.0
        else:
            u = i / float(n)
        fx, fy = _point(u, scale, t)
        # The Specification DAT's origin is lower-left, so y is flipped out of
        # the top-left space the curve is written in.
        lines.append('%d\t%d\t%s' % (int(fx * WIDTH), int((1.0 - fy) * HEIGHT),
                                     ch))
    return '\n'.join(lines)


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
    env = min(1.0, max(0.0,
        1.0 - (t - S.get('kick_t', -1.0e9)) / max(1e-6, KICK_TIME)))

    text, lit = _line_at(S.get('lines') or [], t)
    gain = _section_gain(t)
    try:
        op(SPEC_DAT).text = _spec(text, t, 1.0 + KICK_PUSH * env) if text else 'x\ty\ttext'
    except Exception:
        pass
    _setpar(TEXT_TOP, 'fontsizex', SIZE)
    _setpar(TEXT_TOP, 'fontsizey', SIZE)
    _setpar('orb_text_l', 'brightness1', PEAK * lit * gain)

    ground = FLOOR * gain
    r, g, b = _hsv(HUE, SAT, ground)
    out = np.empty((16, 16, 4), np.float32)
    out[:, :, 0] = r
    out[:, :, 1] = g
    out[:, :, 2] = b
    out[:, :, 3] = 1.0
    scriptOp.copyNumpyArray(np.ascontiguousarray(out))

    S['stats'] = {'line': text, 'lit': round(lit, 3),
                  'chars': max(0, len(text.replace(' ', ''))),
                  'params_missing': PARAMS_MISSING}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS
