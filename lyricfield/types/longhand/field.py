"""Longhand, inside TouchDesigner: a volume of handwriting, and a camera in it.

From the Chainsmokers' "Closer" lyric video, which the sources describe as
"live action footage compiled with lyrics that fly through 3d space", over what
began as a practical effect -- words written on paper and filmed. Two earlier
readings of that reference were wrong in opposite directions: one flew words at
the camera down a tunnel, the other panned along a flat written line. The words
do not move at all. They are scattered through a space, and the eye moves.

So every word is placed ONCE, at a position that is a pure function of its
index. Each frame this script works out where the camera is, projects the words
near it, sorts them into depth slabs by how far away they are, and writes one
Specification DAT per slab.

The slabs are why there is more than one Text TOP: a Text TOP has ONE font size
for its whole Specification DAT, so continuous perspective is not available.
Each slab is fixed at the size its depth calls for, and a word is drawn by
whichever slab is nearest. `params.slab_depths` is the single list both halves
read, so the size a word is drawn at cannot drift from the depth it was placed
at -- which would make the perspective wrong with nothing on screen to say so.

Three things make it read as floating rather than as a slideshow:

  * The camera is always between words. `chase` is greater than one, so it is
    still travelling toward the current word when the next one lands. A camera
    that arrives and waits is a slideshow with a pan.
  * It wanders on its own, from three incommensurable periods, so it never
    repeats and is never quite still.
  * Distance costs size, light and focus together. Any one of them alone reads
    as a flat layer that has been scaled.

Every one of those is a pure function of the cue table and the timestamp. There
is no per-frame integration anywhere, so a dropped frame or a seek cannot
change what is drawn and the song renders the same way twice.
"""

CUE_DAT = 'lyrics'
PARAMS_DAT = 'params'
# One Specification DAT per slab, nearest first: spec0, spec1, ...
SPEC_STEM = 'spec'

DEFAULTS = {
    # `fog`, `haze` and `peak` are not here: they are baked into the Level and
    # Blur TOPs by `build.py`, per slab, and a key in DEFAULTS is a promise the
    # script reads it. `size_at_one` IS here, because the field needs it to
    # work out how wide a word will be before deciding to write the row.
    'width': 720, 'height': 1280, 'size_at_one': 260.0,
    'focus_x': 0.46, 'focus_y': 0.52,
    'spread_x': 1.00, 'spread_y': 0.62, 'near_z': 0.35, 'far_z': 5.00,
    'march': 0.62, 'reach': 9,
    'chase': 1.35, 'standoff': 1.55, 'float_': 0.22, 'float_secs': 11.0,
    'layers': 5,
    'amount': 14.0, 'ceiling': 40.0,
    'hue': 0.09, 'sat': 0.10, 'floor': 0.03,
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

# Roughly how wide a character is, in ems, for a script face. Only used to keep
# a word from being written half out of its own slab, so it does not need to be
# exact -- it needs to be consistent, which a measured advance would not be
# across fonts.
EM = 0.52

# The frame interval the motion blur is measured over. A real frame time would
# make the smear depend on how fast TouchDesigner happens to be cooking, which
# is the whole class of defect this renderer avoids elsewhere.
BLUR_DT = 1.0 / 24.0


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
    g['LAYERS'] = max(2, int(g['LAYERS']))
    g['NEAR_Z'] = max(0.05, float(g['NEAR_Z']))
    g['FAR_Z'] = max(g['NEAR_Z'] * 1.2, float(g['FAR_Z']))
    g['STANDOFF'] = max(g['NEAR_Z'], float(g['STANDOFF']))
    dur = float(g['DURATION'] or 0.0)
    if dur <= 0.0:
        try:
            dur = float(root.time.end) / float(root.time.rate)
        except Exception:
            dur = 0.0
    g['TAIL_END'] = dur
    g['SLABS'] = _slab_depths()
    S.pop('laid', None)
    return P


def _slab_depths():
    """The depth each slab stands at, nearest first.

    The same geometric spacing `params.slab_depths` computes, and it has to
    stay that way: `build.py` fixes each Text TOP's font size from that list,
    and this script decides which slab a word belongs to from this one. If they
    disagreed a word would be drawn at a size that did not match its distance,
    and the perspective would simply be wrong.

    Geometric rather than even because apparent size goes as 1/z: evenly spaced
    slabs put most of them in the far half of the volume, where the difference
    between one and the next is a pixel.
    """
    n = max(2, int(LAYERS))
    near = max(1e-3, NEAR_Z)
    far = max(near * 1.01, FAR_Z)
    ratio = (far / near) ** (1.0 / (n - 1))
    return [near * ratio ** i for i in range(n)]


try:
    _apply_params()
except Exception:
    for _k, _v in DEFAULTS.items():
        globals()[_k.upper()] = _v
    globals()['TAIL_END'] = 0.0
    globals()['SLABS'] = [0.35, 0.6805, 1.3232, 2.5726, 5.0]


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
    """Where every word sits in the volume, once.

    Returns a list of (x, y, z) in depth units, where 1.0 is "as wide as the
    frame at depth 1". The lyrics march away from the start in z so the song
    runs off into the distance rather than piling up in one room; x and y
    wander on two incommensurable periods each, so consecutive words are near
    enough that the camera does not have to swing to find the next one, and far
    enough that they are not stacked.

    A pure function of the index -- no RNG anywhere -- so the same song lays
    out the same way on any machine and a re-render is identical.
    """
    import math

    if 'laid' in S:
        return S['laid']

    # Periods in WORDS, chosen to share no small common multiple: over a verse
    # the path never doubles back on itself in the same place twice.
    wx1, wx2 = 2.0 * math.pi / 6.0, 2.0 * math.pi / 13.0
    wy1, wy2 = 2.0 * math.pi / 7.5, 2.0 * math.pi / 17.0
    out = []
    for i in range(len(cues)):
        x = SPREAD_X * (0.68 * math.sin(i * wx1 + 0.7)
                        + 0.32 * math.sin(i * wx2 + 2.3))
        y = SPREAD_Y * (0.62 * math.sin(i * wy1 + 1.9)
                        + 0.38 * math.sin(i * wy2 + 4.4))
        out.append((x, y, i * MARCH))
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


def _drift(t, seed):
    """A slow wander in -1..1 that never repeats on any useful timescale.

    Three incommensurable periods, the same shape `beat.drift` uses and for the
    same reason: a camera that is perfectly still between words makes every
    word land as a stutter out of a freeze.
    """
    import math

    per = max(0.5, FLOAT_SECS)
    a = math.sin(2.0 * math.pi * t / per + 0.7 + seed * 1.7)
    b = math.sin(2.0 * math.pi * t / (per * 0.61) + 2.3 + seed * 3.1)
    c = math.sin(2.0 * math.pi * t / (per * 0.37) + 4.1 + seed * 5.9)
    return (a + b + c) / 3.0


def _camera(cues, laid, t):
    """Where the camera is, in the volume's own coordinates.

    Eased between the word being sung and the next, over `chase` times the gap
    between their cues -- so at the moment the next word lands the camera is
    only part of the way to the one before it and is still moving. That lag is
    the whole feel; at `chase` 1 it arrives exactly on the beat and the motion
    reads as a series of stops.

    It sits `standoff` in front of whatever it is looking at, so the word being
    sung is ahead of the camera rather than inside it.
    """
    n = len(cues)
    if not n:
        return 0.0, 0.0, -STANDOFF
    i = _at(cues, t)
    if i < 0:
        x, y, z = laid[0]
    elif i >= n - 1:
        x, y, z = laid[-1]
    else:
        gap = max(1e-3, cues[i + 1][0] - cues[i][0])
        u = _smooth((t - cues[i][0]) / (gap * max(1.0, CHASE)))
        a, b = laid[i], laid[i + 1]
        x = a[0] + (b[0] - a[0]) * u
        y = a[1] + (b[1] - a[1]) * u
        z = a[2] + (b[2] - a[2]) * u

    if FLOAT_ > 0.0:
        x += FLOAT_ * SPREAD_X * _drift(t, 0.0)
        y += FLOAT_ * SPREAD_Y * _drift(t, 1.0)
    return x, y, z - STANDOFF


def _project(p, cam):
    """A word's screen position and its distance from the camera.

    Returns (x, y, depth) in pixels and depth units, or None when the word is
    behind the near wall or past the far one.

    Both axes are scaled by the frame's WIDTH, not by their own dimension. A
    step in x covers `width` pixels and a step in y covers `height`, so scaling
    each by its own would stretch the volume into an ellipsoid -- the mistake
    this project made twice in one afternoon, on a sun and on a circle.
    """
    d = p[2] - cam[2]
    if d < NEAR_Z or d > FAR_Z:
        return None
    k = WIDTH / d
    return (FOCUS_X * WIDTH + (p[0] - cam[0]) * k,
            FOCUS_Y * HEIGHT + (p[1] - cam[1]) * k,
            d)


def _slab_of(d):
    """Which slab draws a word at this distance: the nearest in log depth.

    In log depth, because that is the space the slabs are spaced in and the one
    apparent size is linear in -- picking by absolute distance would send
    almost everything to the farthest slab.
    """
    import math

    best, best_err = 0, None
    ld = math.log(max(1e-6, d))
    for i, z in enumerate(SLABS):
        err = abs(ld - math.log(max(1e-6, z)))
        if best_err is None or err < best_err:
            best, best_err = i, err
    return best


def _spec(cues, laid, t, cam, gain):
    """One Specification DAT body per slab: the words near the camera.

    PIXELS FROM THE LOWER LEFT -- the Spec DAT's origin, and the thing that has
    cost time twice in this project. Written top-down the whole volume renders
    upside down, which reads as a broken renderer rather than as an axis slip.
    """
    bodies = [[SPEC_HEAD] for _ in SLABS]
    n = len(cues)
    if not n or gain <= 0.0:
        return ['\n'.join(b) for b in bodies], 0

    i = max(0, min(n - 1, _at(cues, t)))
    drawn = 0
    for j in range(max(0, i - REACH), min(n, i + REACH + 1)):
        seen = _project(laid[j], cam)
        if seen is None:
            continue
        x, y, d = seen
        # A word is written from its centre, so half of it may hang outside the
        # frame and still be worth drawing; much past that and it is a row for
        # nothing.
        half = SIZE_AT_ONE / d * EM * max(1, len(cues[j][1])) * 0.5
        if x + half < -WIDTH * 0.1 or x - half > WIDTH * 1.1:
            continue
        if y < -HEIGHT * 0.15 or y > HEIGHT * 1.15:
            continue
        k = _slab_of(d)
        bodies[k].append('%d\t%d\t%s' % (int(x), int(HEIGHT - y), cues[j][1]))
        drawn += 1
    return ['\n'.join(b) for b in bodies], drawn


def _smear(cues, laid, t):
    """How far the frame has moved since the last frame, in pixels.

    Measured by projecting the camera's own axis one frame ago rather than by
    differencing a stored position: a stored one would make the smear depend on
    whether the previous cook happened, which a seek or a dropped frame breaks.
    A pure function of `t`, like everything else here.
    """
    now = _camera(cues, laid, t)
    was = _camera(cues, laid, t - BLUR_DT)
    # At the standoff depth, which is where the word being sung sits: that is
    # the part of the frame the eye is on.
    k = WIDTH / max(1e-3, STANDOFF)
    dx = (now[0] - was[0]) * k
    dy = (now[1] - was[1]) * k
    # Depth movement reads as a zoom rather than a slide. Counted in, at the
    # scale one frame of it moves a word half a frame out from the axis.
    dz = (now[2] - was[2]) * k * 0.5
    return dx, dy, dz


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
        bodies, drawn = [SPEC_HEAD for _ in SLABS], 0
        cam = (0.0, 0.0, -STANDOFF)
    else:
        cam = _camera(cues, laid, t)
        bodies, drawn = _spec(cues, laid, t, cam, gain)
    for k, body in enumerate(bodies):
        try:
            d = op('%s%d' % (SPEC_STEM, k))
            if d is not None:
                d.text = body
        except Exception:
            pass

    # ---- the smear ---------------------------------------------------------
    # Two taps either side of the frame, so the blur is centred on where the
    # words are rather than trailing behind them. Zero when the camera is
    # still, which between words it never quite is.
    if AMOUNT > 0.0 and not held:
        dx, dy, dz = _smear(cues, laid, t)
        span = math.sqrt(dx * dx + dy * dy + dz * dz) * (AMOUNT / WIDTH)
        span = min(float(CEILING), span)
        if span > 1e-3:
            mag = math.sqrt(dx * dx + dy * dy) or 1.0
            ux, uy = dx / mag, dy / mag
        else:
            ux, uy = 0.0, 0.0
        _setpar('lh_tap_a', 'tx', -span * ux)
        _setpar('lh_tap_a', 'ty', span * uy)
        _setpar('lh_tap_b', 'tx', span * ux)
        _setpar('lh_tap_b', 'ty', -span * uy)
    else:
        span = 0.0
        for tap in ('lh_tap_a', 'lh_tap_b'):
            _setpar(tap, 'tx', 0.0)
            _setpar(tap, 'ty', 0.0)

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
                  'cam': [round(v, 3) for v in cam],
                  'smear': round(span, 2),
                  'gain': round(gain, 3), 'params_missing': PARAMS_MISSING}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS       # no input; must run every frame
