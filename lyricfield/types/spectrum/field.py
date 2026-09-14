"""Spectrum, inside TouchDesigner: the beat as bars.

The only renderer here that draws a *measurement* rather than a reaction. Every
other one answers onsets -- a kick lands, something happens. This one is a
picture of where the energy is, which is a different thing entirely and needs
data none of the others do: `bands.tsv`, pushed into a `bands` table DAT and
looked up by time.

Two behaviours are worth knowing because they are what separates a spectrum
analyser from a row of blocks that jump:

  * a bar rises instantly and falls slowly. A bar chart is only good at showing
    transients, and a slow rise misses every one of them.
  * each bar carries a cap that marks its recent peak and falls back on its own.
    Without them a busy passage is a wall and nothing stands out.

Whole-array: the bars are painted by comparing one height per column against a
precomputed row coordinate, not by looping over pixels.
"""

PARAMS_DAT = 'params'

DEFAULTS = {
    'width': 720, 'height': 1280, 'scale': 0.5,
    'count': 24, 'fill': 0.62, 'reach': 0.68, 'floor_at': 0.92,
    'mirror': False, 'settle': 0.16,
    'on': True, 'thick': 0.006, 'fall': 0.55, 'hang': 0.22,
    'hue': 0.55, 'hue_span': 0.28, 'sat': 0.55,
    'intro_open': 0.30, 'arrive': 0.85, 'outro': 10.0,
    # measured facts, pushed with the params
    'kick_in': 0.0, 'high_in': 0.0, 'duration': 0.0,
}

PARAMS_MISSING = False
BANDS_MISSING = False

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
    g['COUNT'] = max(1, int(g['COUNT']))
    g['MIRROR'] = bool(g['MIRROR'])
    g['ON'] = bool(g['ON'])
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
    """Column and row coordinates, computed once."""
    import numpy as np

    if 'u' in S:
        return S['u'], S['v']
    h = max(8, int(HEIGHT * SCALE))
    w = max(8, int(WIDTH * SCALE))
    S['u'] = ((np.arange(w, dtype=np.float32) + 0.5) / w)[None, :]
    # v runs 0 at the TOP, which is how `floor_at` reads: 0 the top edge, 1 the
    # bottom. The array is flipped once on the way out, in `onCook`.
    S['v'] = ((np.arange(h, dtype=np.float32) + 0.5) / h)[:, None]
    S['shape'] = (h, w)
    return S['u'], S['v']


def _fold(levels, count):
    """The measured bands, averaged down to `count` bars.

    Averaging rather than sampling: taking every Nth band throws away whatever
    fell between, and on a narrow frame that is most of the spectrum.
    """
    n = len(levels)
    if not n:
        return [0.0] * count
    if n == count:
        return list(levels)
    out = []
    for i in range(count):
        a = int(i * n / count)
        b = max(a + 1, int((i + 1) * n / count))
        chunk = levels[a:min(b, n)]
        out.append(sum(chunk) / len(chunk) if chunk else 0.0)
    return out


def _settle(prev, target, dt, seconds):
    """Rise instantly, fall over `seconds`.

    The asymmetry is the whole point: a bar chart exists to show transients, and
    a bar that is slow to rise misses every one of them.
    """
    if target >= prev or seconds <= 0.0 or dt <= 0.0:
        return target
    step = dt / seconds
    return max(target, prev - step)


def _caps(prev, heights, dt):
    """Each bar's peak mark: held at a new peak, then falling.

    Returned as (height, held_until) per bar.
    """
    out = []
    for i, h in enumerate(heights):
        was, until = prev[i] if i < len(prev) else (0.0, -1.0e9)
        if h >= was:
            out.append((h, HANG))
        elif until > 0.0:
            out.append((was, until - dt))
        else:
            out.append((max(h, was - FALL * dt), 0.0))
    return out


def _hsv(h, s, v):
    """HSV to RGB. Scalar: called once per bar, not once per pixel."""
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
    global BANDS_MISSING

    t = float(me.time.seconds)

    try:
        stamp = len(op(PARAMS_DAT).text) if op(PARAMS_DAT) is not None else 0
    except Exception:
        stamp = 0
    if S.get('stamp') != stamp:
        _apply_params()
        S['stamp'] = stamp

    if 'band_t' not in S:
        S['band_t'], S['band_rows'] = _read_bands()
        BANDS_MISSING = not S['band_t']

    u, v = _grids()
    h, w = S['shape']

    dt = max(0.0, t - S.get('t_prev', t))
    S['t_prev'] = t

    raw = _bands_at(S['band_t'], S['band_rows'], t)
    gain = _section_gain(t)
    target = [x * gain for x in _fold(raw, COUNT)]

    prev = S.get('heights') or [0.0] * COUNT
    if len(prev) != COUNT:
        prev = [0.0] * COUNT
    heights = [_settle(prev[i], target[i], dt, SETTLE) for i in range(COUNT)]
    S['heights'] = heights

    caps = _caps(S.get('caps') or [], heights, dt)
    S['caps'] = caps

    # ---- paint -------------------------------------------------------------
    field = np.zeros((h, w), np.float32)
    hue = np.zeros((h, w), np.float32)

    slot = 1.0 / COUNT
    ink = slot * FILL
    base = float(FLOOR_AT)
    for i, hgt in enumerate(heights):
        left = i * slot + (slot - ink) * 0.5
        col = (u >= left) & (u < left + ink)
        if not col.any():
            continue
        top = base - hgt * REACH
        if MIRROR:
            rows = (v >= top) & (v <= base + hgt * REACH)
        else:
            rows = (v >= top) & (v <= base)
        sel = col & rows
        field[sel] = 1.0
        hue[sel] = i / max(1, COUNT - 1)

        if ON:
            cy = base - caps[i][0] * REACH
            cap = col & (v >= cy - THICK) & (v < cy)
            field[cap] = 1.0
            hue[cap] = i / max(1, COUNT - 1)
            if MIRROR:
                cy2 = base + caps[i][0] * REACH
                cap2 = col & (v > cy2) & (v <= cy2 + THICK)
                field[cap2] = 1.0
                hue[cap2] = i / max(1, COUNT - 1)

    out = np.empty((h, w, 4), np.float32)
    # One `_hsv` per bar rather than per pixel: the tint runs across the chart,
    # so every pixel of a bar shares a colour.
    lut = [_hsv(HUE + HUE_SPAN * (i / max(1, COUNT - 1)), SAT, 1.0)
           for i in range(COUNT)]
    reds = np.array([c[0] for c in lut], np.float32)
    greens = np.array([c[1] for c in lut], np.float32)
    blues = np.array([c[2] for c in lut], np.float32)
    idx = np.clip((hue * max(1, COUNT - 1) + 0.5).astype(np.int32),
                  0, COUNT - 1)
    out[:, :, 0] = field * reds[idx]
    out[:, :, 1] = field * greens[idx]
    out[:, :, 2] = field * blues[idx]
    out[:, :, 3] = 1.0
    scriptOp.copyNumpyArray(np.ascontiguousarray(np.flipud(out)))

    S['stats'] = {'bars': COUNT, 'tallest': round(max(heights), 4),
                  'slices': len(S['band_t']), 'gain': round(gain, 3),
                  'bands_missing': BANDS_MISSING,
                  'params_missing': PARAMS_MISSING}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS       # no input; must run every frame
