"""Glitch, inside TouchDesigner: the words, torn.

Three kinds of damage, each on its own drum:

  * blocks of the picture slide sideways -- a kick throws more of them,
  * the red and blue channels pull apart -- a snare widens the gap,
  * CRT scanlines roll down the frame -- the hats deepen them.

The Script TOP here is not the picture and it is not the ground either: it is a
**map**. Red carries the horizontal coordinate to sample, green the vertical,
and blue the scanline mask. A Remap TOP reads the first two and moves the pixels
that are already there, which is what makes a tear read as a damaged signal
rather than as a rectangle pasted over the type.

It is computed at eight pixels wide. That is not a shortcut: the displacement is
constant along a row and the sampled coordinate is *linear* in x, so linear
interpolation back up to frame width is exact rather than approximate. A full
frame of it would be a million floats a frame for no difference at all.
"""

CUE_DAT = 'lyrics'
WORD_DAT = 'gl_words'
PARAMS_DAT = 'params'
PLUS_X = 'gl_plus'
MINUS_X = 'gl_minus'

# The map is this wide. Any width would do; eight keeps the interpolation
# unambiguous and the array small.
MAP_W = 8

DEFAULTS = {
    # No `line_y`: `build` bakes it into the Text TOP's position and
    # nothing here reads it per frame.
    'width': 720, 'height': 1280, 'hold': 2.4,
    'throw': 0.09, 'band': 0.06, 'rest': 0.06,
    'kick_lift': 0.7, 'kick_time': 0.20, 'churn': 9.0,
    'gap': 0.004, 'snare_lift': 0.020, 'snare_time': 0.18,
    'count': 240.0, 'depth': 0.35, 'roll': 42.0,
    'hat_lift': 0.18, 'hat_time': 0.12,
    'intro_open': 0.30, 'arrive': 0.85, 'outro': 10.0,
    # measured facts, pushed with the params
    'kick_in': 0.0, 'high_in': 0.0, 'duration': 0.0, 'hold_windows': (),
    'offset': 0.0,
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
    dur = float(g['DURATION'] or 0.0)
    if dur <= 0.0:
        try:
            dur = float(root.time.end) / float(root.time.rate)
        except Exception:
            dur = 0.0
    g['TAIL_END'] = dur
    S.pop('rows', None)
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


def _env(t, struck, decay):
    """A strike's decay, clamped at BOTH ends -- see halftone for why."""
    return min(1.0, max(0.0, 1.0 - (t - struck) / max(1e-6, decay)))


def _read_cues():
    """The cue table as a list of (start, word, line), in time order."""
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
        try:
            line = int(float(d[r, 2].val.strip()))
        except (ValueError, IndexError, AttributeError):
            line = 0
        if word:
            out.append((start, word, line))
    out.sort(key=lambda x: x[0])
    return out


def _line_at(cues, t):
    """The words of the line being sung, up to and including the current one.

    The line assembles as it is sung rather than appearing whole, which is what
    makes this a lyric renderer rather than a caption with an effect on it.
    """
    shown = []
    line = None
    for start, word, ln in cues:
        if start > t:
            break
        if line is None or ln != line:
            line, shown = ln, []
        if t - start <= HOLD:
            shown.append(word)
    return ' '.join(shown)


def _rows():
    """Every row index, as one array, made once.

    Shared by the tear and the scanlines. It used to be built by `_tear` alone
    and read by `_scan`, which worked only because `onCook` happened to call
    them in that order -- an ordering nothing stated and nothing enforced.
    """
    import numpy as np

    h = HEIGHT
    if S.get('rows_h') != h:
        S['rows_h'] = h
        S['rows'] = np.arange(h, dtype=np.float32)
    return S['rows']


def _tear(t):
    """How far each row of the picture is thrown sideways, as a fraction.

    A row is either torn or it is not -- a smooth displacement is a wobble, not
    a tear, and the difference is the whole look. Which rows are torn reshuffles
    `churn` times a second.
    """
    import numpy as np

    h = HEIGHT
    rows = _rows()

    # Blocks, not rows: the band is what gives a tear its height.
    band_px = max(1.0, float(BAND) * h)
    block = np.floor(rows / band_px)

    # A new pattern every 1/churn seconds. Quantising `t` rather than drawing
    # random numbers keeps the frame a pure function of its own timestamp, so a
    # dropped frame or a seek cannot change what is rendered.
    step = float(int(t * CHURN)) if CHURN > 0 else 0.0

    # Two incommensurable multipliers give a hash that is stable per (block,
    # step) and needs no generator state.
    hsh = np.modf(np.sin(block * 12.9898 + step * 78.233) * 43758.5453)[0]
    hsh = np.abs(hsh)

    share = min(1.0, max(0.0, float(REST)
                         + KICK_LIFT * _env(t, S.get('kick_t', -1.0e9), KICK_TIME)))
    torn = (hsh < share)
    # A second hash decides which way and how far, so torn blocks do not all
    # slide the same distance.
    amt = np.modf(np.sin(block * 4.1414 + step * 21.111) * 24634.6345)[0]
    return np.where(torn, amt * float(THROW), 0.0).astype(np.float32)


def _scan(t):
    """The scanline mask for each row, 0..1, as a multiplier on the picture."""
    import numpy as np

    h = HEIGHT
    rows = _rows()
    depth = min(0.95, max(0.0, float(DEPTH)
                          + HAT_LIFT * _env(t, S.get('hat_t', -1.0e9), HAT_TIME)))
    phase = 2.0 * 3.14159265 * (rows * float(COUNT) / max(1.0, h)
                                + t * float(ROLL) / max(1.0, float(COUNT)))
    return (1.0 - depth * (0.5 + 0.5 * np.sin(phase))).astype(np.float32)


def _setpar(path, name, value):
    """Set a parameter on a sibling, quietly. A missing operator costs the
    picture its motion, not its existence, and raising would stop the cook."""
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
        S['cues'] = _read_cues()

    cues = S.get('cues') or []
    held = _held(t)
    gain = _section_gain(t)

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

    words = '' if held else _line_at(cues, t)
    try:
        op(WORD_DAT).text = words
    except Exception:
        pass

    # The channel split is a Transform TOP either side of the remap, driven from
    # here so it can answer the snare.
    sep = (float(GAP) + SNARE_LIFT
           * _env(t, S.get('snare_t', -1.0e9), SNARE_TIME)) * gain
    _setpar(PLUS_X, 'tx', sep * WIDTH)
    _setpar(MINUS_X, 'tx', -sep * WIDTH)

    # ---- the map ----------------------------------------------------------
    shift = _tear(t) * gain
    scan = _scan(t)
    h = HEIGHT
    xs = (np.arange(MAP_W, dtype=np.float32) + 0.5) / MAP_W
    ys = (np.arange(h, dtype=np.float32) + 0.5) / h

    out = np.empty((h, MAP_W, 4), np.float32)
    # Red: where to sample horizontally. Linear in x, which is what makes an
    # eight-pixel-wide map exact when it is interpolated back up.
    out[:, :, 0] = xs[None, :] + shift[:, None]
    # Green: vertical, untouched -- the tear throws pixels sideways only. Written
    # INVERTED because the whole array is flipped on the way out: a TOP's row 0
    # is the bottom of the frame, so after `flipud` this lands as v = j/h at TD
    # row j, which samples each row from itself. Writing it the obvious way up
    # made every glyph render upside down -- the map told the bottom of the
    # frame to sample the top.
    out[:, :, 1] = 1.0 - ys[:, None]
    out[:, :, 2] = scan[:, None]
    out[:, :, 3] = 1.0
    scriptOp.copyNumpyArray(np.ascontiguousarray(np.flipud(out)))

    S['stats'] = {'words': words, 'torn': int(np.count_nonzero(shift)),
                  'rows': int(h), 'split': round(float(sep), 5),
                  'scan_min': round(float(scan.min()), 4),
                  'gain': round(gain, 3), 'params_missing': PARAMS_MISSING}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS       # no input; must run every frame
