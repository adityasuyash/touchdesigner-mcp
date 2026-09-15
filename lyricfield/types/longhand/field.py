"""Longhand, inside TouchDesigner: a camera travelling a written line.

From the Chainsmokers' "Closer" lyric video. The first attempt at that
reference flew words at the camera through depth slabs, which is not what the
video does: it pans along one long handwritten string of the lyrics, word to
word, and the words before and after the one being sung trail off either side.

So every word is laid out ONCE, in a space the camera moves through. Each frame
this script works out where the camera is, writes the words near it into a
Specification DAT at their screen positions, and dims them by how far they are
from the focus.

Three things make it read as floating rather than as a slideshow, and all three
are deliberate:

  * The camera is always between words. `chase` is greater than one, so it is
    still travelling toward the current word when the next one lands. A camera
    that arrives and waits is a slideshow with a pan.
  * It drifts on its own, slowly, independent of the words.
  * The line itself wanders, from two long incommensurable periods, so the
    travel direction keeps changing and the path never looks ruled.

Every one of those is a pure function of the cue table and the timestamp. There
is no per-frame integration anywhere, so a dropped frame or a seek cannot
change what is drawn and the song renders the same way twice.
"""

CUE_DAT = 'lyrics'
SPEC_DAT = 'spec'
PARAMS_DAT = 'params'

DEFAULTS = {
    'width': 720, 'height': 1280, 'size': 86.0,
    'focus_x': 0.44, 'focus_y': 0.5,
    'gap': 1.6, 'meander': 0.16, 'wander_words': 7.0, 'drift_words': 23.0,
    'tilt': 3.5,
    'chase': 1.35, 'float_': 0.035, 'float_secs': 7.0, 'breathe': 0.05,
    'hue': 0.09, 'sat': 0.10, 'peak': 0.93, 'falloff': 0.42, 'floor': 0.03,
    'reach': 7,
    'kick_lift': 0.06, 'kick_time': 0.25,
    'intro_open': 0.35, 'arrive': 0.88, 'outro': 10.0,
    # measured facts, pushed with the params
    'kick_in': 0.0, 'high_in': 0.0, 'duration': 0.0, 'hold_windows': (),
    'offset': 0.0,
}

PARAMS_MISSING = False

S = {}

INTRO_RAMP = 2.0

# What a Specification DAT needs, and what an empty one holds.
SPEC_HEAD = 'x\ty\ttext'

# Roughly how wide a character is, in ems, for a script face. Only used to
# space words along the line, so it does not need to be exact -- it needs to be
# consistent, which a measured advance would not be across fonts.
EM = 0.52


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
    g['REACH'] = max(1, int(g['REACH']))
    dur = float(g['DURATION'] or 0.0)
    if dur <= 0.0:
        try:
            dur = float(root.time.end) / float(root.time.rate)
        except Exception:
            dur = 0.0
    g['TAIL_END'] = dur
    S.pop('laid', None)
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


def _held(t):
    for w in (HOLD_WINDOWS or ()):
        try:
            a, b = float(w[0]), float(w[1])
        except (TypeError, IndexError, ValueError):
            continue
        if a <= t < b:
            return True
    return False


def _read_cues():
    """The cue table as a list of (start, word), in time order."""
    out = []
    try:
        d = op(CUE_DAT)
    except Exception:
        return out
    if d is None:
        return out
    try:
        rows = d.numRows
    except Exception:
        return out
    for r in range(rows):
        try:
            word = d[r, 0].val.strip()
            start = float(d[r, 1].val.strip())
        except (ValueError, IndexError, AttributeError):
            continue
        if word:
            out.append((start, word))
    out.sort(key=lambda x: x[0])
    return out


def _layout(cues):
    """Where every word sits along the written line, once.

    Returns a list of (along, drop) in PIXELS: `along` is distance travelled up
    the line, `drop` is how far the line has wandered off level at that point.
    Computed once per cue table rather than per frame -- it is the same line
    all the way through, and the camera is the only thing that moves.
    """
    import math

    if 'laid' in S:
        return S['laid']

    space = SIZE * EM * GAP
    out, along = [], 0.0
    # Two long, incommensurable periods, so the wander never looks ruled and
    # does not repeat inside a verse.
    w1 = 2.0 * math.pi / max(1.5, WANDER_WORDS)
    w2 = 2.0 * math.pi / max(2.0, DRIFT_WORDS)
    amp = MEANDER * HEIGHT
    for i, (_start, word) in enumerate(cues):
        drop = amp * (0.68 * math.sin(i * w1 + 0.6)
                      + 0.32 * math.sin(i * w2 + 2.4))
        out.append((along, drop))
        along += SIZE * EM * max(1, len(word)) + space
    S['laid'] = out
    return out


def _at(cues, t):
    """Index of the last cue at or before `t`, or -1. Bisect, not a scan."""
    lo, hi = 0, len(cues)
    while lo < hi:
        mid = (lo + hi) // 2
        if cues[mid][0] <= t:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


def _camera(cues, laid, t):
    """Where the camera is, in the line's own coordinates.

    Eased between the current word and the next, over `chase` times the gap
    between their cues -- so at the moment the next word is sung the camera is
    only part of the way to the one before it and is still moving. That lag is
    the whole feel; with `chase` at 1 it arrives exactly on the beat and the
    motion reads as a series of stops.
    """
    import math

    n = len(cues)
    if not n:
        return 0.0, 0.0
    i = _at(cues, t)
    if i < 0:
        a = laid[0]
        return a[0], a[1]
    if i >= n - 1:
        a = laid[-1]
        along, drop = a[0], a[1]
    else:
        gap = max(1e-3, cues[i + 1][0] - cues[i][0])
        u = _smooth((t - cues[i][0]) / (gap * max(1.0, CHASE)))
        a, b = laid[i], laid[i + 1]
        along = a[0] + (b[0] - a[0]) * u
        drop = a[1] + (b[1] - a[1]) * u

    # ... and a slow float of its own, so even a held word is never static.
    if FLOAT_ > 0.0:
        per = max(0.5, FLOAT_SECS)
        amp = FLOAT_ * HEIGHT
        along += amp * 0.6 * math.sin(2.0 * math.pi * t / per + 0.9)
        drop += amp * math.sin(2.0 * math.pi * t / (per * 1.37) + 2.1)
    return along, drop


def _spec(cues, laid, t, cam_along, cam_drop, gain):
    """The Specification DAT: the words near the camera, at their screen spots.

    PIXELS FROM THE LOWER LEFT -- the Spec DAT's origin, and the thing that has
    cost time twice in this project. Written top-down the whole line renders
    upside down, which reads as a broken renderer rather than as an axis slip.
    """
    import math

    lines = [SPEC_HEAD]
    n = len(cues)
    if not n:
        return '\n'.join(lines), 0

    i = max(0, min(n - 1, _at(cues, t)))
    fx = FOCUS_X * WIDTH
    fy = FOCUS_Y * HEIGHT
    # The line breathes toward and away from the camera, which keeps the whole
    # frame alive between words.
    scale = 1.0 + BREATHE * math.sin(2.0 * math.pi * t / max(0.5, FLOAT_SECS * 1.7))

    drawn = 0
    for j in range(max(0, i - REACH), min(n, i + REACH + 1)):
        along, drop = laid[j]
        x = fx + (along - cam_along) * scale
        y = fy + (drop - cam_drop) * scale
        if x < -WIDTH * 0.6 or x > WIDTH * 1.6:
            continue
        # Dimmed by distance from the word being sung, not by distance in
        # pixels: a long word should not be fainter than a short one.
        dim = max(0.0, 1.0 - abs(j - i) * FALLOFF)
        v = (FLOOR + (PEAK - FLOOR) * dim) * gain
        if v <= FLOOR * 0.5:
            continue
        lines.append('%d\t%d\t%s' % (int(x), int(HEIGHT - y), cues[j][1]))
        drawn += 1
    return '\n'.join(lines), drawn


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
    import math

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
        S['cues'] = _read_cues()

    cues = S.get('cues') or []
    laid = _layout(cues)
    held = _held(t)
    gain = _section_gain(t)

    if held:
        body, drawn = SPEC_HEAD, 0
        along = drop = 0.0
    else:
        along, drop = _camera(cues, laid, t)
        body, drawn = _spec(cues, laid, t, along, drop, gain)
    try:
        op(SPEC_DAT).text = body
    except Exception:
        pass

    # A hand-written line is not perfectly level, and the tilt wanders with the
    # camera rather than sitting at a fixed angle.
    if TILT > 0.0:
        _setpar('lh_text', 'rotate',
                TILT * math.sin(along / max(1.0, WIDTH * 1.7)))

    # ---- the ground --------------------------------------------------------
    if 'drums' not in S:
        S['drums'] = _read_drums()
    since = S.get('t_prev', t)
    S['t_prev'] = t
    if _struck(S['drums']['kick'], t, since):
        S['kick_t'] = t
    # Clamped at both ends: a strike ahead of `t` makes the age negative and an
    # unclamped envelope grows without limit.
    env = min(1.0, max(0.0,
        1.0 - (t - S.get('kick_t', -1.0e9)) / max(1e-6, KICK_TIME)))
    ground = (FLOOR * 0.4 + KICK_LIFT * env) * gain

    r, g, b = _hsv(HUE, SAT, ground)
    out = np.empty((16, 16, 4), np.float32)
    out[:, :, 0] = r
    out[:, :, 1] = g
    out[:, :, 2] = b
    out[:, :, 3] = 1.0
    scriptOp.copyNumpyArray(np.ascontiguousarray(out))

    S['stats'] = {'drawn': drawn, 'cues': len(cues),
                  'along': round(along, 1), 'drop': round(drop, 1),
                  'gain': round(gain, 3), 'params_missing': PARAMS_MISSING}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS       # no input; must run every frame
