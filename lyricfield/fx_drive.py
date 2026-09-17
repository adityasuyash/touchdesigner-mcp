"""The beat response, inside TouchDesigner.

Pushed into a Script TOP the way every renderer's `field.py` is, and it is the
`monument` pattern exactly: the TOP is not the picture. It is sixteen pixels
that nothing looks at, and its job is to read the drum table each frame and set
the parameters of the operators around it.

What it drives:

    fx_shake   transformTOP   tx, ty        the jolt
    fx_zoom    transformTOP   sx, sy        the punch
    fx_split   reorderTOP     (via fx_r/fx_b transforms) the fringe
    fx_bloom   blurTOP        size          the swell
    fx_level   levelTOP       brightness1   the lift that rides with it

Nothing here knows which renderer drew the frame it is moving, which is the
whole point: one chain, every word look.

Every envelope is `impulse` from `lyricfield/beat.py` -- a fast eased attack and
a damped spring that crosses rest and settles -- rather than `1 - age/decay`,
which is what makes a beat effect read as a meter. The same file is imported by
the tests, so the shape asserted there is the shape that runs.
"""

# `fx_params`, not `params`: the renderer's own params DAT is called `params`
# and lives in the words container, and this chain sits at the root beside it.
# Reading the wrong name does not fail -- it falls back to the DEFAULTS below
# and every preset renders as the same picture, which is exactly what happened:
# five previews recorded, `jolt` and `pulse` identical to three decimal places.
PARAMS_DAT = 'fx_params'
# The other operator on this script: the one that draws the dust.
BURST_TOP = 'fx_burst'

DEFAULTS = {
    'width': 720, 'height': 1280,
    'zoom_on': True, 'zoom_drive': 'kick', 'zoom_amount': 1.075,
    'zoom_decay': 0.42, 'zoom_float_': 0.25,
    'bloom_on': True, 'bloom_drive': 'kick', 'bloom_amount': 14.0,
    'bloom_decay': 0.55, 'bloom_lift': 0.22,
    'shake_on': False, 'shake_drive': 'snare', 'shake_amount': 0.012,
    'shake_decay': 0.24, 'shake_tilt': 0.45,
    'split_on': False, 'split_drive': 'snare', 'split_amount': 0.006,
    'split_decay': 0.20,
    'burst_on': False, 'burst_drive': 'kick', 'burst_amount': 1.6,
    'burst_decay': 0.75, 'burst_reach': 0.38, 'burst_rise': 0.35,
    'burst_swirl': 0.5, 'burst_size': 1.6, 'burst_swell': 1.6,
    'offset': 0.0,
}

PARAMS_MISSING = False

S = {}

# Seconds of attack, and the spring's cycles-per-release. Mirrors
# `lyricfield/beat.py`; a test asserts the two agree, because a drift between
# them would mean the preview and the render disagree about the feel.
ATTACK = 0.04
BOUNCE = 0.62
# See `lyricfield/beat.py`. Kept in step by a test.
SPARK = 22.0
STAGGER = 0.25


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
    for k in ('ZOOM_ON', 'BLOOM_ON', 'SHAKE_ON', 'SPLIT_ON', 'BURST_ON'):
        g[k] = bool(g[k])
    S.clear()
    return P


try:
    _apply_params()
except Exception:
    for _k, _v in DEFAULTS.items():
        globals()[_k.upper()] = _v


def _ease(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def _impulse(t, struck, decay, bounce=BOUNCE):
    """See `lyricfield/beat.py:impulse`. Kept in step by a test.

    Clamped at BOTH ends -- a strike ahead of the playhead makes the age
    negative, which a seek makes routine.
    """
    import math

    age = t - struck
    decay = max(1e-6, float(decay))
    if age < 0.0 or age > decay:
        return 0.0
    if age < ATTACK:
        return _ease(age / ATTACK)
    x = (age - ATTACK) / max(1e-6, decay - ATTACK)
    return ((1.0 - x) ** 1.8) * math.cos(math.pi * 2.0 * max(0.0, bounce) * x)


def _drift(t, seed=0.0):
    """A slow wander in -1..1 that never repeats on a useful timescale.

    What keeps the layer moving between hits. Without it every strike reads as
    a stutter out of a freeze, which is the difference between floaty and
    mechanical.
    """
    import math

    # Periods of about 5.6, 8.8 and 17 seconds. The first draft ran at 20-70s,
    # which over a four-second preview is a one-way ramp rather than a wander --
    # slow enough to be invisible is the same as not being there. The phase
    # offsets stop all three starting at zero together, which would make the
    # first second of every render a ramp from nothing.
    a = math.sin(t * 1.1300 + 0.7 + seed * 1.7)
    b = math.sin(t * 0.7130 + 2.3 + seed * 3.1)
    c = math.sin(t * 0.3670 + 4.1 + seed * 5.9)
    return (a + b + c) / 3.0


def _shake_offset(t, env, span, tilt, seed=1.0):
    """See `lyricfield/beat.py:shake_offset`. Kept in step by a test.

    Direction and magnitude are separate. The first version multiplied the
    amplitude by the drift itself, whose mean absolute value is 0.39, so a jolt
    asking for 32 pixels landed as 6 and Jolt read as a dimmer Punch.
    """
    import math

    dx, dy = _drift(t, seed), _drift(t, seed + 1.0)
    n = math.hypot(dx, dy)
    if n < 1e-9:
        dx, dy, n = 1.0, 0.0, 1.0
    # Tilt shapes the direction; it must not shrink the throw. Weighting the
    # axes and stopping there costs about half the amplitude at tilt 0.45, so
    # the vector is renormalised and `amount` is the peak displacement it says
    # it is rather than some fraction of it.
    wx, wy = (dx / n) * (1.0 - tilt), (dy / n) * tilt
    m = math.hypot(wx, wy)
    if m < 1e-9:
        wx, wy, m = (1.0, 0.0, 1.0) if tilt < 0.5 else (0.0, 1.0, 1.0)
    reach = span * env
    return (reach * wx / m, reach * wy / m)


def _hash(i, k):
    """See `lyricfield/beat.py:_hash`. Kept in step by a test."""
    import numpy as np

    x = np.sin(i * 12.9898 + k * 78.233) * 43758.5453
    return x - np.floor(x)


def _burst_points(count, age, life, reach, rise, swirl, span, seed=0.0):
    """See `lyricfield/beat.py:burst_points`. Kept in step by a test.

    Closed form in the age, so a seek draws what a clean playthrough would.
    """
    import math

    import numpy as np

    life = max(1e-6, float(life))
    count = int(max(0, count))
    if count == 0 or age < 0.0 or age >= life * (1.0 + STAGGER):
        z = np.zeros(0, np.float32)
        return z, z, z

    i = np.arange(count, dtype=np.float64)
    r1, r2, r3 = _hash(i, 1.0 + seed), _hash(i, 2.0 + seed), _hash(i, 3.0 + seed)
    r4 = _hash(i, 4.0 + seed)

    # Not every particle leaves at the instant of the strike. Without this they
    # all sit on the lettering together for the first few frames and the word
    # disappears under a white slab -- which is what the first recording of
    # this did, and no amount of dimming fixes it, because the problem is that
    # the light is in one place at one moment rather than that there is too
    # much of it.
    u = (float(age) / life) - r4 * STAGGER
    live = (u >= 0.0) & (u < 1.0)
    u = np.clip(u, 0.0, 1.0)

    ang = r1 * (math.pi * 2.0)
    far = float(reach) * float(span) * (0.35 + 0.65 * r2)
    # Ease-out: (1 - (1-u)^2) is 0 at the strike, steep immediately after, flat
    # by the end of the life.
    d = far * (1.0 - (1.0 - u) ** 2)

    dx = np.cos(ang) * d
    # Sideways is squashed and the rise is added on top, so the cloud is taller
    # than it is wide -- measured on the GHOSTS clip at 0.20 of the width
    # against 0.22 of the height, on a frame twice as tall as it is wide.
    dy = np.sin(ang) * d * 0.8 + float(rise) * float(reach) * float(span) * (u ** 1.6)

    w = float(swirl) * float(span) * 0.05 * (u ** 1.5)
    dx += w * np.sin(r3 * (math.pi * 2.0) + 3.1 * u)
    dy += w * np.cos(r2 * (math.pi * 2.0) + 2.3 * u)

    # Dark until it is off the letters, so the type stays legible through its
    # own burst: `u^0.45` is nearly zero for the first frames of a particle's
    # life and full by a fifth of the way through.
    bright = ((1.0 - u) ** 1.7) * (0.45 + 0.55 * r3) * (u ** 0.45) * live
    return (dx.astype(np.float32), dy.astype(np.float32),
            bright.astype(np.float32))


def _taps(size):
    """See `lyricfield/beat.py:taps`. Kept in step by a test."""
    out = [(0, 0, 1.0)]
    size = float(size)
    if size > 1.0:
        e = min(1.0, size - 1.0)
        out += [(1, 0, e), (-1, 0, e), (0, 1, e), (0, -1, e)]
    if size > 2.0:
        e = min(1.0, size - 2.0) * 0.7
        out += [(1, 1, e), (1, -1, e), (-1, 1, e), (-1, -1, e)]
    return tuple(out)


def _major(drums, struck, kind, window=0.06):
    """See `lyricfield/beat.py:major`. Kept in step by a test."""
    for other, times in (drums or {}).items():
        # Hats do not count. They play continuously -- in the shipped preview
        # table there is one on every kick -- so "a hat landed with it" is true
        # of every hit there is, and every burst came out the bigger size.
        if other == kind or other == 'hat':
            continue
        for t in times:
            if abs(t - struck) <= window:
                return True
    return False


def _since(kind, t, back):
    """Every strike of `kind` in (t - back, t], oldest first.

    The burst needs all the bursts still in the air, not only the last one --
    at a 0.9s life and 120bpm there are two of them at any moment.
    """
    times = S.get('drums', {}).get(kind) or ()
    return [x for x in times if t - back < x <= t]


def _last(kind, t):
    """When the most recent `kind` landed at or before `t`.

    A lookup rather than edge detection: an effect needs to know how far
    through a response it is, not whether one just started, and an edge that
    fires once cannot answer that after a seek.
    """
    times = S.get('drums', {}).get(kind) or ()
    if not times:
        return -1.0e9
    lo, hi = 0, len(times)
    while lo < hi:
        mid = (lo + hi) // 2
        if times[mid] <= t:
            lo = mid + 1
        else:
            hi = mid
    return times[lo - 1] if lo else -1.0e9


def _setpar(path, name, value):
    """Set a parameter on a sibling, quietly.

    A missing operator costs the picture its motion, not its existence, and
    raising here would stop the cook.
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
    """No custom parameters; see monument for why none rather than one."""
    return


def onPulse(par):
    return


def _emitters(scriptOp, struck, count):
    """Where a burst starts, and what colour it is.

    From the TYPE itself: the input is the word layer at a quarter resolution,
    and the particles leave the glyphs' own EDGES -- the BioCloud reference
    sheds from a surface, not out of a solid. An erosion is four shifted
    comparisons on the mask, which is nothing at this size.

    The sample is taken once, when the burst fires, and kept for its life. On a
    linear render -- which is what a render is -- that is exactly the frame the
    strike landed on. Scrubbing backwards past a burst re-seeds it, so a scrub
    can differ from a render for up to one particle lifetime; re-sampling every
    frame instead would make the particles jump whenever the word changes,
    which is worse and visible.
    """
    import numpy as np

    try:
        src = scriptOp.inputs[0]
        a = src.numpyArray(delayed=False)
    except Exception:
        return None
    if a is None or a.ndim != 3 or a.shape[0] < 4 or a.shape[1] < 4:
        return None

    # The brightest CHANNEL, not the luminance. A saturated blue at full value
    # has a luminance of 0.24, so a luminance threshold finds no type at all in
    # a blue-inked look and the burst silently draws nothing -- which is the
    # whole failure mode this chain exists to avoid.
    m = a[:, :, :3].max(axis=2) > 0.3
    inner = np.zeros_like(m)
    inner[1:-1, 1:-1] = (m[1:-1, 1:-1] & m[:-2, 1:-1] & m[2:, 1:-1]
                         & m[1:-1, :-2] & m[1:-1, 2:])
    edge = m & ~inner
    idx = np.flatnonzero(edge)
    if idx.size == 0:
        idx = np.flatnonzero(m)
    if idx.size == 0:
        return None

    h, w = m.shape
    rng = np.random.default_rng(int(abs(struck) * 1000.0) & 0x7FFFFFFF)
    pick = idx[rng.integers(0, idx.size, int(count))]
    ys = (pick // w).astype(np.float32) + rng.random(int(count), np.float32)
    xs = (pick % w).astype(np.float32) + rng.random(int(count), np.float32)

    # The dust carries the type's own colour, so a blue-inked look throws blue
    # dust and nothing here has to know which renderer drew the frame. One
    # colour for the burst rather than one per particle: the lettering is one
    # colour, and it turns three splats per tap into one.
    rgb = a.reshape(-1, a.shape[2])[pick, :3].mean(axis=0)
    top = float(rgb.max())
    col = (rgb / top) if top > 1e-4 else np.ones(3, np.float32)
    return xs / float(w), ys / float(h), col.astype(np.float32)


def _draw_burst(scriptOp, t):
    """The dust, as a picture. The other half of this file's job.

    Everything else here sets parameters on its neighbours; this one IS the
    frame. It draws every burst still in the air into a half-resolution buffer
    and the chain scales, glows and clamps it.

    Splatted with `bincount` on a flat index rather than `np.add.at`: measured
    in TouchDesigner's own Python, 40k points into a 360x640 buffer cost
    3.2ms a frame through `add.at` and 0.37ms through `bincount`.
    """
    import numpy as np

    # The buffer is sized from the PUSHED frame, not from `scriptOp.width`.
    # A Script TOP's resolution is whatever its script last wrote -- the
    # resolution parameters are set and then ignored -- so asking the operator
    # how big it is answers "2x2" on the first cook and then stays there
    # forever, because the script obligingly writes 2x2 again. Measured: the
    # first recording of this drew a 2x2 image stretched over the whole frame,
    # which is why the dust came out as one enormous soft blob.
    w = max(2, int(WIDTH) // 2)
    h = max(2, int(HEIGHT) // 2)
    out = np.zeros((h, w, 4), np.float32)
    out[:, :, 3] = 1.0
    if not BURST_ON:
        scriptOp.copyNumpyArray(np.ascontiguousarray(out))
        return 0

    life = max(1e-6, float(BURST_DECAY))
    span = float(min(w, h))
    kind = BURST_DRIVE
    base = int(max(0.0, float(BURST_AMOUNT)) * 1000.0)
    cache = S.setdefault('burst', {})
    alive = _since(kind, t, life * (1.0 + STAGGER))
    for k in list(cache):
        if k not in alive:
            del cache[k]

    drawn = 0
    for struck in alive:
        big = _major(S.get('drums'), struck, kind)
        count = int(base * (float(BURST_SWELL) if big else 1.0))
        if count <= 0:
            continue
        seeded = cache.get(struck)
        if seeded is None:
            seeded = _emitters(scriptOp, struck, count)
            if seeded is None:
                continue
            cache[struck] = seeded
        ex, ey, col = seeded
        n = min(count, ex.size)
        reach = float(BURST_REACH) * (float(BURST_SWELL) if big else 1.0)

        # Both kernels sum to one, so `size` changes how soft a particle is and
        # the trail how long it is, and NEITHER changes how much light a burst
        # puts on the frame. Unnormalised, the two together multiplied it by
        # six and the first recording was a solid white slab.
        kern = _taps(float(BURST_SIZE))
        kw = sum(abs(k[2]) for k in kern) or 1.0
        trail = ((0.0, 1.0), (0.06, 0.55), (0.12, 0.28))
        tw = sum(k[1] for k in trail)

        flats, wts = [], []
        # Three samples along the particle's OWN past, at falling brightness:
        # the trail-from-its-own-past that CLAUDE.md endorses, and what turns
        # dots into the strands both references show.
        for lag, weight in trail:
            age = (t - struck) - lag * life
            dx, dy, br = _burst_points(n, age, life, reach, float(BURST_RISE),
                                       float(BURST_SWIRL), span)
            if dx.size == 0:
                continue
            xs = ex[:n] * w + dx
            ys = ey[:n] * h + dy
            for ox, oy, ow in kern:
                xi = (xs + ox).astype(np.int32)
                yi = (ys + oy).astype(np.int32)
                keep = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
                if not keep.any():
                    continue
                flats.append(yi[keep] * w + xi[keep])
                wts.append(br[keep] * (SPARK * (weight / tw) * (ow / kw)))
            drawn += n
        if not flats:
            continue
        # ONE bincount for the whole burst. Its cost is the size of the buffer
        # and not the number of points, so fifteen of them -- one per tap per
        # trail sample -- cost fifteen passes over a quarter of a million
        # floats: measured at 5.0ms a frame against 0.6ms for this.
        face = np.bincount(np.concatenate(flats),
                           weights=np.concatenate(wts),
                           minlength=h * w).astype(np.float32).reshape(h, w)
        for c in range(3):
            out[:, :, c] += face * float(col[c])

    scriptOp.copyNumpyArray(np.ascontiguousarray(out))
    return drawn


def onCook(scriptOp):
    import numpy as np

    t = float(me.time.seconds) + float(OFFSET or 0.0)

    try:
        stamp = len(op(PARAMS_DAT).text) if op(PARAMS_DAT) is not None else 0
    except Exception:
        stamp = 0
    if S.get('stamp') != stamp:
        _apply_params()
        S['stamp'] = stamp

    if 'drums' not in S:
        S['drums'] = _read_drums()

    # Two Script TOPs share this one script and tell themselves apart by name.
    # One DAT rather than two: a second pushed script is a second thing that
    # can be stale or never written, and a Script TOP with empty callbacks
    # draws black and reports nothing.
    if scriptOp.name == BURST_TOP:
        S['burst_drawn'] = _draw_burst(scriptOp, t)
        return

    # ---- zoom: the punch ---------------------------------------------------
    if ZOOM_ON:
        env = _impulse(t, _last(ZOOM_DRIVE, t), ZOOM_DECAY)
        travel = float(ZOOM_AMOUNT) - 1.0
        # The breath under it, so a held frame is never perfectly still.
        breathe = travel * float(ZOOM_FLOAT_) * 0.5 * _drift(t, 0.0)
        scale = 1.0 + travel * env + breathe
        _setpar('fx_zoom', 'sx', scale)
        _setpar('fx_zoom', 'sy', scale)
    else:
        _setpar('fx_zoom', 'sx', 1.0)
        _setpar('fx_zoom', 'sy', 1.0)

    # ---- shake: the jolt ---------------------------------------------------
    if SHAKE_ON:
        env = _impulse(t, _last(SHAKE_DRIVE, t), SHAKE_DECAY)
        span = float(SHAKE_AMOUNT) * min(WIDTH, HEIGHT)
        tx, ty = _shake_offset(t, env, span, float(SHAKE_TILT))
        _setpar('fx_shake', 'tx', tx)
        _setpar('fx_shake', 'ty', ty)
    else:
        _setpar('fx_shake', 'tx', 0.0)
        _setpar('fx_shake', 'ty', 0.0)

    # ---- split: the fringe -------------------------------------------------
    if SPLIT_ON:
        env = _impulse(t, _last(SPLIT_DRIVE, t), SPLIT_DECAY)
        gap = float(SPLIT_AMOUNT) * WIDTH * env
        _setpar('fx_r', 'tx', gap)
        _setpar('fx_b', 'tx', -gap)
    else:
        _setpar('fx_r', 'tx', 0.0)
        _setpar('fx_b', 'tx', 0.0)

    # ---- bloom: the swell --------------------------------------------------
    lift = 0.0
    if BLOOM_ON:
        env = _impulse(t, _last(BLOOM_DRIVE, t), BLOOM_DECAY)
        # Only the positive half lifts the glow: a blur radius below rest would
        # mean sharpening, which a Blur TOP cannot do and would clamp anyway.
        up = max(0.0, env)
        _setpar('fx_bloom', 'size', float(BLOOM_AMOUNT) * up)
        lift = float(BLOOM_LIFT) * up
    else:
        _setpar('fx_bloom', 'size', 0.0)

    # These sixteen pixels ARE the lift, and the chain multiplies the word
    # layer by them and adds the result -- `word * (1 + lift)`, which is what
    # `fx_level.brightness1` used to be set to.
    #
    # That it is a signal rather than a parameter write is the point. With no
    # outputs this operator was in nobody's cook chain and TouchDesigner never
    # ran it: every render came out untouched while the params, the drum table
    # and the whole chain beside it were correct. `CookLevel.ALWAYS` says how
    # OFTEN to cook, not whether anyone is asking.
    out = np.zeros((16, 16, 4), np.float32)
    out[:, :, 0] = lift
    out[:, :, 1] = lift
    out[:, :, 2] = lift
    out[:, :, 3] = 1.0
    scriptOp.copyNumpyArray(np.ascontiguousarray(out))

    S['stats'] = {'params_missing': PARAMS_MISSING,
                  'on': [n for n, v in (('zoom', ZOOM_ON), ('bloom', BLOOM_ON),
                                        ('shake', SHAKE_ON), ('split', SPLIT_ON),
                                        ('burst', BURST_ON))
                         if v],
                  'burst_drawn': S.get('burst_drawn', 0),
                  'drums': {k: len(v) for k, v in (S.get('drums') or {}).items()}}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS       # no input; must run every frame
