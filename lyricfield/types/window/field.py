"""Window, inside TouchDesigner: the light moves, the words are the hole.

The Script TOP draws a field of drifting bands, shoved by the kick and
roughened by the hi-hats. A Text TOP sets the line being sung. A Matte TOP puts
the first through the second, so the letterforms are made of moving light and
everything outside them is near-black.

This is the only renderer here where the lyric half and the beat half are one
picture rather than two families.

Whole-array throughout: the coordinate grids are built once and every frame is
a handful of broadcasts over them.
"""

CUE_DAT = 'lyrics'
LINE_DAT = 'line'
TEXT_TOP = 'win_text'
PARAMS_DAT = 'params'

DEFAULTS = {
    'width': 720, 'height': 1280, 'scale': 0.5,
    'size': 112.0, 'lead': 0.35, 'hold': 0.9, 'fade': 0.45,
    'line_y': 0.5, 'wrap': 12,
    'bands': 4.5, 'drift': 0.45, 'warp': 0.35,
    'kick_push': 0.38, 'kick_time': 0.35,
    'hat_grain': 0.18, 'hat_time': 0.18,
    'hue': 0.52, 'sat': 0.5, 'peak': 0.92, 'floor': 0.03,
    'intro_open': 0.35, 'arrive': 0.85, 'outro': 11.0,
    'kick_in': 0.0, 'high_in': 0.0, 'duration': 0.0, 'offset': 0.0,
}

PARAMS_MISSING = False

S = {}

INTRO_RAMP = 2.0


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
    g['WIDTH'] = int(g['WIDTH'])
    g['HEIGHT'] = int(g['HEIGHT'])
    g['WRAP'] = int(g['WRAP'])
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


def _read_lines():
    """The cue table grouped into lines: [(first_start, last_start, text)].

    A line at a time rather than a word at a time, because this renderer's
    subject is something you read rather than something that flashes.
    """
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
    by_line = {}
    order = []
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
        rows.append((ws[0][0], ws[-1][0], ' '.join(w for _, w in ws)))
    rows.sort()
    return rows


def _wrap(text, width):
    """Break a line so it fits, without splitting a word."""
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
    """The line to show at `t`, and how lit it is.

    A line comes up `lead` before its first word and goes `hold` after its
    last, so nothing is ever a race to read.
    """
    best, lit = '', 0.0
    for first, last, text in lines:
        a = first - LEAD
        b = last + HOLD
        if t < a or t > b + FADE:
            continue
        if t <= b:
            best, lit = text, 1.0
        else:
            gone = (t - b) / max(1e-6, FADE)
            v = max(0.0, 1.0 - gone)
            if v > lit:
                best, lit = text, v
    return best, lit


def _grids():
    """Normalised x and y for every pixel, built once."""
    import numpy as np

    if 'x' in S:
        return S['x'], S['y']
    h = max(8, int(HEIGHT * SCALE))
    w = max(8, int(WIDTH * SCALE))
    ys = np.linspace(0.0, 1.0, h, dtype=np.float32)
    xs = np.linspace(0.0, 1.0, w, dtype=np.float32)
    S['y'] = ys[:, None]
    S['x'] = xs[None, :]
    S['shape'] = (h, w)
    return S['x'], S['y']


def _field(t, kick_env, hat_env):
    """Drifting bands, bent by a slow warp and shoved by the kick."""
    import numpy as np

    x, y = _grids()
    # The bands travel down the frame; `warp` bends them across it so they are
    # never flat stripes.
    phase = y * BANDS - DRIFT * BANDS * t
    phase = phase + WARP * np.sin(x * 6.28318 + t * 0.35)
    band = 0.5 + 0.5 * np.sin(6.28318 * phase)
    # A kick pushes the whole thing brighter and briefly compresses it.
    v = band * (1.0 + KICK_PUSH * kick_env)
    if HAT_GRAIN > 0.0 and hat_env > 0.0:
        g = 0.5 + 0.5 * np.sin(x * 210.0 + y * 130.0 + t * 9.0)
        v = v + HAT_GRAIN * hat_env * g
    return v


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
    if _struck(S['drums']['hat'], t, since):
        S['hat_t'] = t
    # Clamped at both ends: a strike ahead of the playhead makes the gap
    # negative and an uncapped envelope grows without limit.
    kick_env = min(1.0, max(0.0,
        1.0 - (t - S.get('kick_t', -1.0e9)) / max(1e-6, KICK_TIME)))
    hat_env = min(1.0, max(0.0,
        1.0 - (t - S.get('hat_t', -1.0e9)) / max(1e-6, HAT_TIME)))

    text, lit = _line_at(S.get('lines') or [], t)
    try:
        op(LINE_DAT).text = _wrap(text, WRAP) if text else ''
    except Exception:
        pass
    _setpar(TEXT_TOP, 'fontsizex', SIZE)
    _setpar(TEXT_TOP, 'fontsizey', SIZE)
    # Where the line sits. `positiony` is in the unit `positionunit` names,
    # which the builder sets to pixels for the same reason the font size is in
    # pixels: anything else and the placement follows the display.
    _setpar(TEXT_TOP, 'positiony', (0.5 - LINE_Y) * HEIGHT)

    gain = _section_gain(t) * lit
    v = _field(t, kick_env, hat_env)
    v = FLOOR + (PEAK - FLOOR) * np.clip(v, 0.0, 1.0)
    v = np.clip(v * gain, 0.0, 1.0)

    cr, cg, cb = _hsv(HUE, SAT, 1.0)
    h, w = S['shape']
    out = np.empty((h, w, 4), np.float32)
    out[:, :, 0] = v * cr
    out[:, :, 1] = v * cg
    out[:, :, 2] = v * cb
    out[:, :, 3] = 1.0
    scriptOp.copyNumpyArray(np.ascontiguousarray(np.flipud(out)))

    S['stats'] = {'line': text, 'lit': round(lit, 3),
                  'mean': round(float(v.mean()), 5),
                  'params_missing': PARAMS_MISSING}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS
