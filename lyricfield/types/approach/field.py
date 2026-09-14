"""Approach, inside TouchDesigner: the words come toward you.

From the Chainsmokers' "Closer", where the lyrics travel through 3D space. A
word is born far away at its cue, grows as it comes, and passes the camera about
the time the next one arrives.

The awkward part, and the reason this renderer is shaped the way it is: a Text
TOP has ONE font size for its whole Specification DAT. Continuous perspective is
therefore not available. The space is cut into slabs instead -- each a Text TOP
fixed at the size that depth calls for -- and every frame this script decides
which slab each live word belongs in and writes it there. Brightness and a blur
on the farthest slab supply the fog.

The Script TOP itself is not the picture. It is sixteen pixels of ground: the
floor brightness, a glow at the vanishing point, lifted by the kick.
"""

CUE_DAT = 'lyrics'
PARAMS_DAT = 'params'

DEFAULTS = {
    'width': 720, 'height': 1280,
    'vanish_x': 0.5, 'vanish_y': 0.46,
    'far_z': 7.0, 'near_z': 0.55, 'seconds': 2.6, 'spread': 0.42,
    # No `size_at_one`, `fog` or `peak`: `build` bakes those into the slabs'
    # font sizes and Level TOPs, and nothing here reads them per frame. A key
    # in this dict is a promise that the renderer uses the value.
    'layers': 5,
    'hue': 0.58, 'sat': 0.18, 'floor': 0.02,
    'kick_lift': 0.09, 'kick_time': 0.22,
    'intro_open': 0.32, 'arrive': 0.85, 'outro': 10.0,
    # measured facts, pushed with the params
    'kick_in': 0.0, 'high_in': 0.0, 'duration': 0.0, 'hold_windows': (),
    'offset': 0.0,
}

PARAMS_MISSING = False

S = {}

INTRO_RAMP = 2.0

# The header every Specification DAT needs, and what an empty slab holds. A
# Text TOP with a spec table of only this draws nothing, which is what a slab
# with no words in it should do.
SPEC_HEAD = 'x\ty\ttext'


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
    g['LAYERS'] = max(2, int(g['LAYERS']))
    dur = float(g['DURATION'] or 0.0)
    if dur <= 0.0:
        try:
            dur = float(root.time.end) / float(root.time.rate)
        except Exception:
            dur = 0.0
    g['TAIL_END'] = dur
    S.pop('slabs', None)
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
    """Where in the piece this is, as a multiplier on the ground."""
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


def _slabs():
    """The depth of each slab, nearest first.

    Geometric, not linear: apparent size goes as 1/z, so linear spacing would
    make the near slabs identical to each other and the far ones jump. Mirrors
    `params.slab_depths`, which `build` uses to set the font sizes -- the two
    have to agree or a word is drawn at a size that does not match its depth.
    """
    if 'slabs' in S:
        return S['slabs']
    lo = max(1e-6, float(NEAR_Z))
    hi = max(lo * 1.0001, float(FAR_Z))
    n = LAYERS
    ratio = hi / lo
    S['slabs'] = [lo * (ratio ** (i / (n - 1.0))) for i in range(n)]
    return S['slabs']


def _slab_for(z):
    """Index of the slab a word at depth `z` should be drawn by.

    Nearest in the log of depth rather than in depth itself, for the same
    reason the slabs are spaced that way: halfway between 1 and 7 in size terms
    is not 4.
    """
    slabs = _slabs()
    best, bd = 0, None
    lz = z if z > 1e-6 else 1e-6
    import math
    for i, sz in enumerate(slabs):
        d = abs(math.log(lz) - math.log(sz))
        if bd is None or d < bd:
            best, bd = i, d
    return best


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


def _offset_for(i):
    """Where word `i` sits off the centre line, as (dx, dy) in frame units.

    Deterministic in the word's index rather than random per frame, so a word
    holds its lane all the way in -- and so the whole piece renders the same way
    twice, which a per-frame random would quietly break.
    """
    # Two incommensurable constants: cheap, stable, and no generator state.
    a = (i * 0.7548776662) % 1.0
    b = (i * 0.5698402909) % 1.0
    return (a - 0.5) * 2.0 * SPREAD, (b - 0.5) * 2.0 * SPREAD


def _depth_at(t, start):
    """How deep word `start` is at `t`, travelling from far_z to near_z.

    Linear in depth, which is what constant velocity means. Apparent size then
    grows as 1/z, so a word drifts for most of its life and then rushes the last
    part -- which is the whole feel of the reference.
    """
    frac = (t - start) / max(1e-6, float(SECONDS))
    return float(FAR_Z) + (float(NEAR_Z) - float(FAR_Z)) * frac


def _live(cues, t):
    """Every word in flight at `t`, as (slab, x_px, y_px, word).

    Coordinates are in PIXELS FROM THE LOWER LEFT, because that is the
    Specification DAT's origin. Writing them top-down puts the words upside
    down in the frame, which is the sort of thing that reads as "the renderer
    is broken" rather than as an axis mistake.
    """
    out = []
    n = len(cues)
    if not n:
        return out
    # Only the words whose journey could still be running: a linear scan of a
    # wordy song every frame is avoidable and this runs at 60fps.
    span = float(SECONDS)
    lo = _at(cues, t - span)
    for i in range(max(0, lo), n):
        start, word = cues[i]
        if start > t:
            break
        z = _depth_at(t, start)
        if z <= float(NEAR_Z) or z > float(FAR_Z):
            continue
        dx, dy = _offset_for(i)
        # The projection: an offset that is `dx` wide at depth 1 is dx/z wide
        # at depth z.
        fx = float(VANISH_X) + dx / z
        fy = float(VANISH_Y) + dy / z
        px = int(fx * WIDTH)
        py = int((1.0 - fy) * HEIGHT)          # spec DAT origin is lower-left
        out.append((_slab_for(z), px, py, word))
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


def _specs(live, layers):
    """One Specification DAT body per slab."""
    rows = [[SPEC_HEAD] for _ in range(layers)]
    for slab, px, py, word in live:
        if 0 <= slab < layers:
            rows[slab].append('%d\t%d\t%s' % (px, py, word))
    return ['\n'.join(r) for r in rows]


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

    live = [] if held else _live(cues, t)
    bodies = _specs(live, LAYERS)
    for i, body in enumerate(bodies):
        try:
            d = op('spec%d' % i)
            if d is not None:
                d.text = body
        except Exception:
            pass

    # ---- the ground -------------------------------------------------------
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
    ground = (FLOOR + KICK_LIFT * env) * gain

    r, g, b = _hsv(HUE, SAT, ground)
    out = np.empty((16, 16, 4), np.float32)
    out[:, :, 0] = r
    out[:, :, 1] = g
    out[:, :, 2] = b
    out[:, :, 3] = 1.0
    scriptOp.copyNumpyArray(np.ascontiguousarray(out))

    S['stats'] = {'live': len(live), 'cues': len(cues),
                  'slabs': [sum(1 for w in live if w[0] == i)
                            for i in range(LAYERS)],
                  'ground': round(ground, 4), 'gain': round(gain, 3),
                  'params_missing': PARAMS_MISSING}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS       # no input; must run every frame
