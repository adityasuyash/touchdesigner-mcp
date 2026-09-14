"""Monument, inside TouchDesigner: one word, as large as it will go.

Every other renderer here composes a picture out of a grid of cells. This one
picks a word, decides how big it is and where it sits, and lets a Text TOP draw
it. The Script TOP is sixteen pixels square -- it is the ground and the hand
that moves the type, not the type itself.

What it does each frame:

  * find the word the cue table says is being sung,
  * write it into `word`, and the one before into `word_prev`,
  * set the two Text TOPs' size, scale and vertical position,
  * and output the ground: the floor brightness, lifted by a kick, gained by
    where in the song this is.

Nothing here is imported from the grid types. There are no rows, no columns and
no glyphs, and there is no Feedback TOP -- the afterimage is the previous word
drawn explicitly, because feedback renders identically only when frame one is
clean.
"""

CUE_DAT = 'lyrics'
WORD_DAT = 'word'
PREV_DAT = 'word_prev'
NOW_TOP = 'mon_now'
WAS_TOP = 'mon_was'
NOW_X = 'mon_now_x'
WAS_X = 'mon_was_x'
PARAMS_DAT = 'params'

# The fallbacks, and the mirror of what the params DAT is expected to carry.
# Every key here is read below: a key in this dict is a promise the renderer
# uses the value, which a meta-test enforces.
DEFAULTS = {
    'width': 720, 'fill': 0.86, 'cap_px': 300.0,
    'line_y': 0.5,
    'punch': 1.16, 'settle': 0.20, 'hold': 0.55, 'fade': 0.30,
    'ghost': 0.20, 'ghost_scale': 1.5, 'drift': 0.035,
    'hue': 0.06, 'sat': 0.22, 'peak': 0.88, 'floor': 0.02,
    'kick_lift': 0.10, 'kick_time': 0.20,
    'intro_open': 0.35, 'arrive': 0.85, 'outro': 10.0,
    # measured facts, pushed with the params
    'kick_in': 0.0, 'high_in': 0.0, 'duration': 0.0, 'hold_windows': (),
    'offset': 0.0,
}

# Set when the params DAT could not be read. Reported through the stats dict
# rather than swallowed, so a renderer running on fallbacks says so.
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
    out = {}
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
    dur = float(g['DURATION'] or 0.0)
    if dur <= 0.0:
        try:
            dur = float(root.time.end) / float(root.time.rate)
        except Exception:
            dur = 0.0
    g['TAIL_END'] = dur
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
    """Where in the piece this is, as a multiplier on the whole picture."""
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
    """Is this inside a measured silence? Nothing is drawn through one."""
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
    # A header row is normal; a row whose start will not parse is skipped
    # rather than fatal, because one bad cell should not blank the whole song.
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


def _at(cues, t):
    """The index of the word being sung at `t`, or -1 before the first.

    Bisect rather than a scan: a wordy song has hundreds of cues and this runs
    every frame.
    """
    lo, hi = 0, len(cues)
    while lo < hi:
        mid = (lo + hi) // 2
        if cues[mid][0] <= t:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


def _fit(word, fill, cap, width):
    """The font size at which `word` fills `fill` of the frame.

    Courier-like faces advance about 0.6 em per character, which is close
    enough for any monospaced or humanist face to land inside the frame; the
    cap is what stops a one-letter word becoming a texture.
    """
    n = max(1, len(word))
    return max(8.0, min(float(cap), (float(width) * float(fill)) / (n * 0.6)))


def _life(t, start, nxt):
    """How lit a word is at `t`, and how far through its life it is.

    A word holds until the next one lands, or for `hold` seconds if it is the
    last; then it fades. Returned as (brightness 0..1, age in seconds).
    """
    age = t - start
    if age < 0.0:
        return 0.0, age
    ends = (nxt if nxt is not None else start + HOLD)
    if t <= ends:
        return 1.0, age
    gone = (t - ends) / max(1e-6, FADE)
    return max(0.0, 1.0 - gone), age


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


def _setpar(path, name, value):
    """Set a parameter on a sibling, quietly.

    The field script drives the two Text TOPs and their transforms every frame.
    A missing operator is survivable -- the picture loses its motion, not its
    existence -- and raising here would stop the cook entirely.
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
    """No custom parameters.

    Deliberately none rather than one that is ignored: `sync` pushes a
    `Cueoffset` onto whatever Script TOP it finds and tolerates its absence,
    and this renderer reads its offset from the params DAT like everything
    else. Declaring one here would also raise on a reassignment, which is how
    two other renderers became unpushable.
    """
    return


def onPulse(par):
    return


def onCook(scriptOp):
    import numpy as np

    t = float(me.time.seconds) + float(OFFSET or 0.0)

    # Reload when the cue table or the params change. `numRows` is cheap and
    # changes whenever either is pushed.
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

    word, prev = '', ''
    lit, age = 0.0, 0.0
    if cues and not held:
        i = _at(cues, t)
        if i >= 0:
            start, word = cues[i]
            nxt = cues[i + 1][0] if i + 1 < len(cues) else None
            lit, age = _life(t, start, nxt)
            if lit <= 0.0:
                word = ''
            if i > 0:
                prev = cues[i - 1][1]

    # ---- the type ---------------------------------------------------------
    # Size is per word, because a long word and a short one should both fill
    # the frame rather than both use one size.
    # Both axes, or the glyphs come out at whatever aspect the y default
    # happens to be -- which is how a font's row pitch silently depended on
    # the display DPI in an earlier renderer here.
    if word:
        px = _fit(word, FILL, CAP_PX, WIDTH)
        _setpar(NOW_TOP, 'fontsizex', px)
        _setpar(NOW_TOP, 'fontsizey', px)
    if prev:
        px = _fit(prev, FILL, CAP_PX, WIDTH)
        _setpar(WAS_TOP, 'fontsizex', px)
        _setpar(WAS_TOP, 'fontsizey', px)

    # The punch: struck at its cue, settling to 1.0 over `settle`.
    k = max(0.0, 1.0 - (age / max(1e-6, SETTLE))) if lit > 0.0 else 0.0
    scale = 1.0 + (PUNCH - 1.0) * k
    # ... and the drift, so a held word is never completely static.
    life = min(1.0, age / max(1e-6, HOLD + FADE)) if lit > 0.0 else 0.0
    ty = (0.5 - LINE_Y) * 2.0 - DRIFT * life

    _setpar(NOW_X, 'scale1', scale)
    _setpar(NOW_X, 'scale2', scale)
    _setpar(NOW_X, 'ty', ty)
    _setpar(WAS_X, 'scale1', GHOST_SCALE)
    _setpar(WAS_X, 'scale2', GHOST_SCALE)
    _setpar(WAS_X, 'ty', ty)

    # Brightness carries the fade and where in the song this is.
    _setpar('mon_now_l', 'brightness1', PEAK * lit * gain)
    _setpar('mon_was_l', 'brightness1', GHOST * gain * (1.0 - k))

    try:
        op(WORD_DAT).text = word
        op(PREV_DAT).text = prev if GHOST > 0.0 else ''
    except Exception:
        pass

    # ---- the ground -------------------------------------------------------
    # A kick lifts the room rather than the word: the word belongs to the cue
    # table, the room belongs to the beat.
    if 'drums' not in S:
        S['drums'] = _read_drums()
    since = S.get('t_prev', t)
    if _struck(S['drums']['kick'], t, since):
        S['kick_t'] = t
    S['t_prev'] = t
    env = max(0.0, 1.0 - (t - S.get('kick_t', -1.0e9)) / max(1e-6, KICK_TIME))
    ground = (FLOOR + KICK_LIFT * env) * gain

    r, g, b = _hsv(HUE, SAT, ground)
    out = np.empty((16, 16, 4), np.float32)
    out[:, :, 0] = r
    out[:, :, 1] = g
    out[:, :, 2] = b
    out[:, :, 3] = 1.0
    scriptOp.copyNumpyArray(np.ascontiguousarray(out))

    S['stats'] = {'word': word, 'lit': round(lit, 3), 'gain': round(gain, 3),
                  'ground': round(ground, 4), 'cues': len(cues),
                  'params_missing': PARAMS_MISSING}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS       # no input; must run every frame
