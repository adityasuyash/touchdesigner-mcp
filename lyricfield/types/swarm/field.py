"""Swarm, inside TouchDesigner: words fly in, settle, and are knocked apart.

Physical, but not a physical *simulation*. Bullet and the Particle SOP step per
cook, so a dropped frame or a seek changes what they produce and a song does
not render the same way twice. Here the integrator is re-run from the line's
own start on every frame -- a few hundred steps over a handful of words, which
is nothing -- so a frame is a pure function of its timestamp and seeking to the
middle of a song gives exactly what playing to it would.

Each word is a spring-damper pulled toward its place in the line, thrown in from
a direction decided by its index, and shoved outward by every kick that has
landed since the line appeared.
"""

CUE_DAT = 'lyrics'
SPEC_DAT = 'spec'
TEXT_TOP = 'swm_text'
PARAMS_DAT = 'params'

DEFAULTS = {
    'width': 720, 'height': 1280,
    'throw': 0.55, 'stiff': 26.0, 'damp': 5.2, 'stagger': 0.06,
    'push': 1.35, 'spin': 0.5,
    'size': 60.0, 'lead': 0.35, 'hold': 1.0, 'fade': 0.45,
    'gap': 0.085, 'per_row': 3,
    'hue': 0.12, 'sat': 0.3, 'peak': 0.95, 'floor': 0.02,
    'intro_open': 0.35, 'arrive': 0.85, 'outro': 11.0,
    'kick_in': 0.0, 'high_in': 0.0, 'duration': 0.0, 'offset': 0.0,
}

PARAMS_MISSING = False

S = {}

INTRO_RAMP = 2.0
# Fixed, and small enough that the spring is stable at any stiffness the
# ranges allow. Not the frame rate: the physics must not change if the render
# runs at a different one.
DT = 1.0 / 120.0
MAX_STEPS = 900


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
    for k in ('WIDTH', 'HEIGHT', 'PER_ROW'):
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
        rows.append((ws[0][0], ws[-1][0], [w for _, w in ws]))
    rows.sort(key=lambda r: r[0])
    return rows


def _line_at(lines, t):
    """The line on screen at `t`, when it appeared, and how lit it is."""
    best, lit, born = None, 0.0, 0.0
    for first, last, words in lines:
        a, b = first - LEAD, last + HOLD
        if t < a or t > b + FADE:
            continue
        if t <= b:
            best, lit, born = words, 1.0, a
        else:
            v = max(0.0, 1.0 - (t - b) / max(1e-6, FADE))
            if v > lit:
                best, lit, born = words, v, a
    return best, lit, born


def _targets(n):
    """Where each word comes to rest, in 0..1 frame space."""
    rows = (n + PER_ROW - 1) // PER_ROW
    out = []
    for i in range(n):
        r, c = divmod(i, PER_ROW)
        wide = min(PER_ROW, n - r * PER_ROW)
        x = (c + 0.5) / float(wide)
        y = 0.5 + (r - (rows - 1) * 0.5) * GAP
        out.append((0.12 + 0.76 * x, y))
    return out


def _settle(words, born, t, kicks):
    """Integrate every word from the line's start to `t`.

    Re-run from scratch rather than carried frame to frame: that is what makes
    this seek-proof and identical on a re-render. A handful of words over a few
    hundred fixed steps is far cheaper than it sounds.
    """
    import math

    n = len(words)
    tgt = _targets(n)
    px, py, vx, vy = [], [], [], []
    for i in range(n):
        # The direction a word is thrown from is decided by its index, so it is
        # the same every time this is run rather than random per frame.
        a = (i * 2.39996) % 6.28318
        px.append(tgt[i][0] + THROW * math.cos(a))
        py.append(tgt[i][1] + THROW * math.sin(a))
        vx.append(0.0)
        vy.append(0.0)

    steps = int(min(MAX_STEPS, max(0.0, t - born) / DT))
    fired = 0
    for s in range(steps):
        now = born + s * DT
        # Every kick that has landed since the line appeared shoves the words
        # outward from the centre, with a little sideways so it is not purely
        # radial.
        while fired < len(kicks) and kicks[fired] <= now:
            for i in range(n):
                dx, dy = px[i] - 0.5, py[i] - 0.5
                d = math.hypot(dx, dy) or 1e-6
                vx[i] += PUSH * (dx / d) - PUSH * SPIN * (dy / d)
                vy[i] += PUSH * (dy / d) + PUSH * SPIN * (dx / d)
            fired += 1
        for i in range(n):
            # A word held back by `stagger` simply is not pulled yet.
            if now - born < i * STAGGER:
                continue
            ax = STIFF * (tgt[i][0] - px[i]) - DAMP * vx[i]
            ay = STIFF * (tgt[i][1] - py[i]) - DAMP * vy[i]
            vx[i] += ax * DT
            vy[i] += ay * DT
            px[i] += vx[i] * DT
            py[i] += vy[i] * DT
    return list(zip(px, py))


def _spec(words, pos):
    """One row per word: x, y, text. The origin is lower-left."""
    lines = ['x\ty\ttext']
    for (fx, fy), word in zip(pos, words):
        # Off-frame words are dropped rather than clamped to the edge, where
        # they would pile up in a stripe.
        if not (-0.2 <= fx <= 1.2 and -0.2 <= fy <= 1.2):
            continue
        lines.append('%d\t%d\t%s' % (int(fx * WIDTH),
                                     int((1.0 - fy) * HEIGHT), word))
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

    words, lit, born = _line_at(S.get('lines') or [], t)
    if words:
        kicks = [k for k in S['drums']['kick'] if born <= k <= t]
        pos = _settle(words, born, t, kicks)
        text = _spec(words, pos)
    else:
        text = 'x\ty\ttext'
    try:
        op(SPEC_DAT).text = text
    except Exception:
        pass
    _setpar(TEXT_TOP, 'fontsizex', SIZE)
    _setpar(TEXT_TOP, 'fontsizey', SIZE)
    gain = _section_gain(t)
    _setpar('swm_text_l', 'brightness1', PEAK * lit * gain)

    r, g, b = _hsv(HUE, SAT, FLOOR * gain)
    out = np.empty((16, 16, 4), np.float32)
    out[:, :, 0] = r
    out[:, :, 1] = g
    out[:, :, 2] = b
    out[:, :, 3] = 1.0
    scriptOp.copyNumpyArray(np.ascontiguousarray(out))

    S['stats'] = {'words': len(words or ()), 'lit': round(lit, 3),
                  'rows': max(0, len(text.split('\n')) - 1),
                  'params_missing': PARAMS_MISSING}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS
