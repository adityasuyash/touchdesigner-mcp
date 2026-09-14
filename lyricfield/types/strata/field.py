"""Strata, inside TouchDesigner: the beat as solid bands.

A kick slams one band to full and it falls back; the next kick takes the next
band, so the stack is played rather than flashed. A snare shoves every band
sideways and they slide back. The hi-hats are a fast fine flicker.

Hard edges throughout -- no gaussians, no falloff, nothing soft. `rings` is the
curved, centred, soft renderer; this is the straight, stacked, hard one, and
the two should be impossible to confuse from a single frame.
"""

PARAMS_DAT = 'params'

DEFAULTS = {
    'width': 720, 'height': 1280, 'scale': 0.75,
    'count': 9, 'gap': 0.22, 'rest': 0.10, 'lit': 0.88,
    'decay': 0.42, 'walk': 3,
    'amount': 0.16, 'snap': 0.30,
    'lift': 0.13, 'fade': 0.13, 'rows': 41.0,
    'hue': 0.09, 'sat': 0.55, 'floor': 0.015,
    'intro_open': 0.28, 'arrive': 0.82, 'outro': 12.0,
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
    for k in ('WIDTH', 'HEIGHT', 'COUNT', 'WALK'):
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


def _shape():
    if 'shape' not in S:
        S['shape'] = (max(8, int(HEIGHT * SCALE)), max(8, int(WIDTH * SCALE)))
    return S['shape']


def _band_index():
    """Which band every row belongs to, and whether it is a gap.

    Built once. The gap is what makes these read as bars rather than as one
    gradient, so it is part of the geometry rather than a brightness trick.
    """
    import numpy as np

    if 'idx' in S:
        return S['idx'], S['ink']
    h, w = _shape()
    rows = np.arange(h, dtype=np.float32)
    pos = rows / h * COUNT                 # 0..count across the frame
    idx = np.floor(pos).astype(np.int32)
    within = pos - idx                     # 0..1 inside a band
    S['idx'] = np.clip(idx, 0, COUNT - 1)
    # Hard edge, not a falloff: inside the gap the band simply is not there.
    S['ink'] = (within >= GAP).astype(np.float32)
    return S['idx'], S['ink']


def _levels(t):
    """How lit each band is, as a list of `count` numbers."""
    out = []
    struck = S.get('struck', {})
    for i in range(COUNT):
        when = struck.get(i)
        if when is None or t < when:
            out.append(REST)
            continue
        # Clamped at both ends; see rings for what an uncapped envelope does.
        env = min(1.0, max(0.0, 1.0 - (t - when) / max(1e-6, DECAY)))
        out.append(REST + (LIT - REST) * env)
    return out


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

    idx, ink = _band_index()
    h, w = _shape()

    if 'drums' not in S:
        S['drums'] = _read_drums()
    since = S.get('t_prev', t)
    S['t_prev'] = t
    if _struck(S['drums']['kick'], t, since):
        # Walk to the next band rather than always hitting the same one: a
        # stack that only ever lights one row is a blinking bar, not a stack.
        nxt = (S.get('at', -WALK) + WALK) % max(1, COUNT)
        S['at'] = nxt
        S.setdefault('struck', {})[nxt] = t
    if _struck(S['drums']['snare'], t, since):
        S['snare_t'] = t
        S['snare_dir'] = -S.get('snare_dir', -1)
    if _struck(S['drums']['hat'], t, since):
        S['hat_t'] = t

    levels = np.asarray(_levels(t), np.float32)
    field = levels[idx] * ink                     # (h,) -> per row
    field = np.repeat(field[:, None], w, axis=1)

    # A snare shears the whole stack sideways and it slides back.
    env = min(1.0, max(0.0,
        1.0 - (t - S.get('snare_t', -1.0e9)) / max(1e-6, SNAP)))
    if AMOUNT > 0.0 and env > 0.0:
        shift = int(round(AMOUNT * w * env * S.get('snare_dir', 1)))
        if shift:
            # Whole bands move together, and alternate rows move opposite ways,
            # so it reads as a shear rather than as the picture sliding.
            odd = (idx % 2 == 1)
            rolled = np.roll(field, shift, axis=1)
            back = np.roll(field, -shift, axis=1)
            field = np.where(odd[:, None], rolled, back)

    # The hi-hats: a fast fine flicker that only shows in the gaps, so it
    # never fights the bands themselves.
    henv = min(1.0, max(0.0,
        1.0 - (t - S.get('hat_t', -1.0e9)) / max(1e-6, FADE)))
    if LIFT > 0.0 and henv > 0.0:
        rows = np.arange(h, dtype=np.float32)[:, None]
        fl = (np.sin(rows * ROWS + t * 40.0) > 0.0).astype(np.float32)
        field = field + LIFT * henv * fl * (1.0 - ink[:, None])

    field = np.clip((FLOOR + field) * _section_gain(t), 0.0, 1.0)

    cr, cg, cb = _hsv(HUE, SAT, 1.0)
    out = np.empty((h, w, 4), np.float32)
    out[:, :, 0] = field * cr
    out[:, :, 1] = field * cg
    out[:, :, 2] = field * cb
    out[:, :, 3] = 1.0
    scriptOp.copyNumpyArray(np.ascontiguousarray(np.flipud(out)))

    S['stats'] = {'at': S.get('at'), 'mean': round(float(field.mean()), 5),
                  'peak': round(float(field.max()), 4),
                  'params_missing': PARAMS_MISSING}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS
