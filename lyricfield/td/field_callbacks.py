# Runs INSIDE TouchDesigner as the Script TOP callbacks. Not importable standalone:
# it depends on TD globals (op, root, me) and is synced into the .toe by
# lyricfield.td.sync. Edit it here, in the repo -- never in the DAT.
#
# Outputs at COLS x VROWS, one pixel per grid cell:
#   RGB   = the DIM layer's colour for that cell
#   ALPHA = the LIT layer's weight (drives the bold text layer)
# and writes two character DATs: chars_dim (regular weight), chars_lit (bold).
# A cell may appear in both during a cue ramp -- dim at (1-w), lit at w -- which
# cross-fades the weight change instead of popping.
#
# THE BEAT IS EXPRESSED ONLY AS LIGHT. Nothing scales, nothing swaps glyphs.
#   KICK  -> RADIAL RIPPLE: a ring of brightness expands from a random grid point,
#            lifting letters by a gaussian falloff on |distance - radius|.
#   SNARE -> SCATTERED SPARKS: a scatter of letters spikes toward SPARK_PEAK and
#            decays, reshuffling each hit. Capped below the 1.0 reserved for cues.
#   INTRO -> STAGGERED TWINKLE on a tempo grid, until the kick enters.
#   LOW   -> glow brightness downstream only; it drives no geometry.
#
# Ripple and spark contributions are built as whole-grid numpy arrays once per
# frame, so the per-letter loop stays a cheap lookup.
#
# Word text is read from the cue table DAT at runtime; none is stored here.

import numpy as np

def _params():
    """Params live in a sibling Text DAT written by lyricfield.sync. A plain
    `import` cannot see a DAT -- TD exposes them through mod() instead."""
    try:
        return mod('params').P
    except Exception:
        return None


P = _params()


def _p(name, default):
    """Parameter lookup: config file if synced, else the baked default."""
    if P is not None and name in P:
        return P[name]
    return default


COLS = 24
BAND = 22            # rows 1..22; must leave BAND_TOP..VROWS-1 room
VROWS = 24
BAND_TOP = 1

DIM_HUE = 0.58
DIM_SAT = 0.35
LEVEL_MIN = 0.10
LEVEL_MAX = 0.38
DRIFT_MIN = 3.0
DRIFT_MAX = 6.0

RAMP_UP = 0.12
HOLD = 0.80
RAMP_DN = 0.25
LEAD = 0.15
DISSOLVE = 2.5

RIPPLE_TIME = 0.55
RIPPLE_SIGMA = 2.2
RIPPLE_LIFT = 0.14

SPARK_TIME = 0.25
SPARK_PEAK = 0.52    # glow stacks on top; 0.75 measured 0.99 at out
SPARK_FRAC = 0.055

CEIL = 0.58          # hard ceiling for any non-cued cell before glow

TWINKLE_FRAC_LO = 0.04
TWINKLE_FRAC_HI = 0.11
TWINKLE_DECAY = 0.22
TWINKLE_LIFT = 0.20

AMBIENT_TARGET = 190
AMBIENT_CYCLE = 6.0
TAIL_END = 91.0

STANZA_SIZE = 5
GAP_MIN, GAP_MAX = 2, 4

# Structure of the instrumental stem, measured by lyricfield.analysis.
# Overridden per-track by the synced params; these are the fallback.
KICK_IN = 29.55
BEAT_ANCHOR = 15.0
BEAT_PERIOD = 0.4615
HIGH_IN = 15.0
HOLD_WINDOWS = ((27.72, 29.53), (57.30, 58.40), (88.65, 1.0e9))

# Operator names as they exist in the project (relative to /project1).
CUE_DAT = 'lyrics'
DIM_DAT = 'v7_chars_dim'
LIT_DAT = 'v7_chars_lit'
ANALYSIS_CHOP = 'v6_aa'

S = {}


def _smooth(a):
    """smoothstep: eases in and out instead of kinking at each target change."""
    a = min(1.0, max(0.0, a))
    return a * a * (3.0 - 2.0 * a)


def _cues():
    """[(word, start_seconds, line), ...] from the cue table DAT."""
    d = op(CUE_DAT)
    out = []
    for r in range(d.numRows):
        w = d[r, 0].val.strip()
        if not w or w.lower() == 'word':
            continue
        try:
            t = float(d[r, 1].val.strip())
            ln = int(float(d[r, 2].val.strip()))
        except (ValueError, IndexError):
            continue
        out.append((w, t, ln))
    out.sort(key=lambda x: x[1])
    return out


def _lines(cues):
    d = {}
    for w, t, ln in cues:
        d.setdefault(ln, []).append((w, t))
    for ln in d:
        d[ln].sort(key=lambda x: x[1])
    return d


def _stanzas(lines):
    keys = sorted(lines)
    out, n, last_end = {}, 0, 0.0
    for i in range(0, len(keys), STANZA_SIZE):
        grp = keys[i:i + STANZA_SIZE]
        ts = [t for ln in grp for _, t in lines[ln]]
        end = max(ts) + RAMP_UP + HOLD + RAMP_DN
        out[n] = {'lines': grp, 'start': min(ts) - LEAD - DISSOLVE,
                  'end': end, 'ambient': False, 'rot': n}
        last_end = end
        n += 1
    # ambient stanzas carry the instrumental tail so the grid is never empty
    t0 = last_end
    while t0 < _p('tail_end', TAIL_END):
        out[n] = {'lines': [], 'start': t0 - DISSOLVE * 0.5,
                  'end': min(_p('tail_end', TAIL_END), t0 + AMBIENT_CYCLE) + DISSOLVE,
                  'ambient': True, 'rot': n}
        t0 += AMBIENT_CYCLE
        n += 1
    return out


def _init():
    S['rng'] = np.random.default_rng(7)
    S['cues'] = _cues()
    S['lines'] = _lines(S['cues'])
    S['stanzas'] = _stanzas(S['lines'])
    S['key'] = op(CUE_DAT).text
    S['stanza'] = None
    S['cur'] = None
    S['prev'] = None
    S['levels'] = {}
    S['rings'] = []
    S['spark_t'] = np.full((VROWS, COLS), -1.0e9, np.float32)
    S['last_kick'] = 0.0
    S['last_snare'] = 0.0
    S['last_t'] = -1.0
    S['twinkle'] = set()
    S['twinkle_t'] = None
    S['beat_i'] = -1
    S['hold_anchor'] = None
    S['stats'] = {}


def _held(t):
    for a, b in _p('hold_windows', HOLD_WINDOWS):
        if a <= t < b:
            return True
    return False


def _hsv(h, s, v):
    k = int(h * 6.0) % 6
    f = h * 6.0 - int(h * 6.0)
    p = v * (1.0 - s); q = v * (1.0 - f * s); t = v * (1.0 - (1.0 - f) * s)
    return [(v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q)][k]


def _level(key, t, rng):
    ent = S['levels'].get(key)
    if ent is None:
        v0 = float(rng.uniform(LEVEL_MIN, LEVEL_MAX))
        v1 = float(rng.uniform(LEVEL_MIN, LEVEL_MAX))
        S['levels'][key] = (v0, v1, t, t + float(rng.uniform(DRIFT_MIN, DRIFT_MAX)))
        return v0
    v0, v1, t0, t1 = ent
    if t >= t1:
        v0 = v1
        v1 = float(rng.uniform(LEVEL_MIN, LEVEL_MAX))
        S['levels'][key] = (v0, v1, t, t + float(rng.uniform(DRIFT_MIN, DRIFT_MAX)))
        return v0
    return v0 + (v1 - v0) * _smooth((t - t0) / max(1e-6, t1 - t0))


def _lay_line(words, claimed, rng):
    """One continuous path per line: words intact, one blank cell between letters,
    GAP_MIN..GAP_MAX between words, blank row skipped on each wrap. Horizontal
    (left-to-right) or vertical (top-to-bottom) only -- never diagonal or reversed."""
    for _ in range(600):
        orient = 'h' if rng.integers(0, 2) == 0 else 'v'
        r = int(rng.integers(BAND_TOP, BAND_TOP + BAND))
        c = int(rng.integers(0, COLS))
        out, used, ok = {}, set(), True
        for wi, (w, _t) in enumerate(words):
            span = 2 * len(w) - 1
            if orient == 'h' and c + span > COLS:
                c = 0; r += 2
            elif orient == 'v' and r + span > BAND_TOP + BAND:
                r = BAND_TOP; c += 2
            if r < BAND_TOP or r >= BAND_TOP + BAND or c < 0 or c >= COLS:
                ok = False; break
            cells, rr, cc, step = [], r, c, 0
            for _i in range(span):
                if rr >= BAND_TOP + BAND or cc >= COLS:
                    ok = False; break
                if step % 2 == 0:
                    cells.append((rr, cc))
                step += 1
                if orient == 'h':
                    cc += 1
                    if cc >= COLS:
                        cc = 0; rr += 2
                else:
                    rr += 1
                    if rr >= BAND_TOP + BAND:
                        rr = BAND_TOP; cc += 2
            if not ok or len(cells) != len(w) or any(x in claimed or x in used for x in cells):
                ok = False; break
            out[wi] = cells
            used.update(cells)
            gap = int(rng.integers(GAP_MIN, GAP_MAX + 1))
            lr, lc = cells[-1]
            if orient == 'h':
                r, c = lr, lc + 1 + gap
                if c >= COLS:
                    c = 0; r += 2
            else:
                r, c = lr + 1 + gap, lc
                if r >= BAND_TOP + BAND:
                    r = BAND_TOP; c += 2
        if ok and len(out) == len(words):
            return out
    return None


def _build(si, t, rng):
    """Lay the stanza, then top up with ambient lines until AMBIENT_TARGET letters."""
    info = S['stanzas'][si]
    claimed, paths, apaths, letters = set(), {}, {}, 0
    if not info['ambient']:
        order = sorted(info['lines'],
                       key=lambda l: -sum(len(w) for w, _ in S['lines'][l]))
        for ln in order:
            got = _lay_line(S['lines'][ln], claimed, rng)
            if got:
                paths[ln] = got
                for cl in got.values():
                    claimed.update(cl); letters += len(cl)
    pool = [ln for ln in sorted(S['lines']) if ln not in paths]
    if pool:
        k = info['rot'] % len(pool)
        pool = pool[k:] + pool[:k]
    for ln in pool:
        if letters >= AMBIENT_TARGET:
            break
        got = _lay_line(S['lines'][ln], claimed, rng)
        if got:
            apaths[ln] = got
            for cl in got.values():
                claimed.update(cl); letters += len(cl)
    stag = {}
    for tag, grp in (('c', paths), ('a', apaths)):
        for ln, pth in grp.items():
            for wi, cells in pth.items():
                for j in range(len(cells)):
                    stag[(tag, ln, wi, j)] = float(rng.uniform(0.0, DISSOLVE * 0.55))
    return {'si': si, 'paths': paths, 'apaths': apaths, 't0': t, 'stag': stag,
            'letters': letters}


def _lit_weight(t, cue):
    if t < cue:
        return 0.0
    if t < cue + RAMP_UP:
        return _smooth((t - cue) / RAMP_UP)
    if t < cue + RAMP_UP + HOLD:
        return 1.0
    if t < cue + RAMP_UP + HOLD + RAMP_DN:
        return 1.0 - _smooth((t - cue - RAMP_UP - HOLD) / RAMP_DN)
    return 0.0


def onSetupParameters(scriptOp):
    return


def onPulse(par):
    return


def onCook(scriptOp):
    if 'rng' not in S or S.get('key') != op(CUE_DAT).text:
        _init()

    t = root.time.seconds
    prev_t = S['last_t']
    if prev_t < 0 or t < prev_t:            # first cook or a backward scrub
        S['stanza'] = None; S['cur'] = None; S['prev'] = None
        S['levels'] = {}; S['rings'] = []
        S['spark_t'] = np.full((VROWS, COLS), -1.0e9, np.float32)
        S['twinkle'] = set(); S['twinkle_t'] = None
        S['beat_i'] = -1; S['hold_anchor'] = None
    S['last_t'] = t
    off = float(scriptOp.par.Cueoffset.eval())
    rng = S['rng']

    held = _held(t)
    if held and S['hold_anchor'] is None:
        S['hold_anchor'] = t
    elif not held:
        S['hold_anchor'] = None
    t_level = S['hold_anchor'] if held else t     # freezes drift while held

    aa = op(ANALYSIS_CHOP)
    kv = float(aa['kick'].eval()) if aa else 0.0
    sv = float(aa['snare'].eval()) if aa else 0.0
    hv = float(aa['high'].eval()) if aa else 0.0

    if (not held) and kv > 0.5 >= S['last_kick']:
        S['rings'].append({'r': float(rng.integers(BAND_TOP, BAND_TOP + BAND)),
                           'c': float(rng.integers(0, COLS)), 't0': t})
    if (not held) and sv > 0.5 >= S['last_snare']:
        n = max(1, int(BAND * COLS * SPARK_FRAC))
        rr = rng.integers(BAND_TOP, BAND_TOP + BAND, size=n)
        cc = rng.integers(0, COLS, size=n)
        S['spark_t'][rr, cc] = t
    S['last_kick'] = kv
    S['last_snare'] = sv

    # ---- whole-grid light contributions, vectorised ----
    gr = np.arange(VROWS, dtype=np.float32).reshape(-1, 1)
    gc = np.arange(COLS, dtype=np.float32).reshape(1, -1)
    ripple = np.zeros((VROWS, COLS), np.float32)
    maxr = float(np.hypot(BAND, COLS))
    alive = []
    for ring in S['rings']:
        age = t - ring['t0']
        if age < 0 or age > RIPPLE_TIME * 1.35:
            continue
        rad = (age / RIPPLE_TIME) * maxr
        d = np.sqrt((gr - ring['r']) ** 2 + (gc - ring['c']) ** 2)
        amp = RIPPLE_LIFT * max(0.0, 1.0 - age / (RIPPLE_TIME * 1.35))
        ripple = np.maximum(ripple, amp * np.exp(-((d - rad) / RIPPLE_SIGMA) ** 2))
        alive.append(ring)
    S['rings'] = alive

    spark_env = np.clip(1.0 - (t - S['spark_t']) / SPARK_TIME, 0.0, 1.0).astype(np.float32)

    kick_in = _p('kick_in', KICK_IN)
    twinkle_on = (t < kick_in) and not held
    if twinkle_on:
        anchor = _p('beat_anchor', BEAT_ANCHOR)
        period = _p('beat_period', BEAT_PERIOD)
        bi = int(np.floor((t - anchor) / period))
        if bi != S['beat_i']:
            S['beat_i'] = bi
            frac = TWINKLE_FRAC_LO if t < _p('high_in', HIGH_IN) else \
                TWINKLE_FRAC_LO + (TWINKLE_FRAC_HI - TWINKLE_FRAC_LO) * min(1.0, hv * 2.0)
            n = max(1, int(BAND * COLS * frac))
            rr = rng.integers(BAND_TOP, BAND_TOP + BAND, size=n)
            cc = rng.integers(0, COLS, size=n)
            S['twinkle'] = set(zip(rr.tolist(), cc.tolist()))
            S['twinkle_t'] = t
    else:
        S['twinkle'] = set()
    tw_env = 0.0
    if twinkle_on and S.get('twinkle_t') is not None:
        tw_env = max(0.0, 1.0 - (t - S['twinkle_t']) / TWINKLE_DECAY)

    # ---- stanza selection: latest that has begun, so overlaps resolve forward ----
    cur_si, best = None, -1e9
    for si, info in S['stanzas'].items():
        s0, e0 = info['start'] + off, info['end'] + off
        if s0 <= t <= e0 and s0 > best:
            best, cur_si = s0, si
    if cur_si != S['stanza']:
        S['prev'] = S['cur'] if S['cur'] is not None else None
        if S['prev'] is not None:
            S['prev']['fade_t0'] = t
        S['stanza'] = cur_si
        S['levels'] = {}
        S['cur'] = _build(cur_si, t, rng) if cur_si is not None else None

    rgb = np.zeros((VROWS, COLS, 3), np.float32)
    alpha = np.zeros((VROWS, COLS), np.float32)
    dim_ch = np.full((VROWS, COLS), ' ', dtype='<U1')
    lit_ch = np.full((VROWS, COLS), ' ', dtype='<U1')
    counts = {'letters': 0, 'lit': 0, 'ambient': 0, 'rippled': 0, 'sparked': 0}

    def draw(group, fade, tag, pth_key, allow_lit):
        if group is None:
            return
        for ln, pth in group[pth_key].items():
            words = S['lines'][ln]
            for wi, cells in pth.items():
                word, wt = words[wi]
                w_lit = _lit_weight(t, wt + off) if allow_lit else 0.0
                for j, (r, c) in enumerate(cells):
                    f = fade(group['stag'].get((tag, ln, wi, j), 0.0))
                    if f <= 0.001:
                        continue
                    counts['letters'] += 1
                    if not allow_lit:
                        counts['ambient'] += 1
                    v = _level((tag, ln, wi, j), t_level, rng)
                    rp = float(ripple[r, c])
                    if rp > 0.005:
                        v = min(CEIL, v + rp)
                        counts['rippled'] += 1
                    se = float(spark_env[r, c])
                    if se > 0.0:
                        v = max(v, SPARK_PEAK * _smooth(se))
                        counts['sparked'] += 1
                    if tw_env > 0.0 and (r, c) in S['twinkle']:
                        v = min(CEIL, v + TWINKLE_LIFT * tw_env * 0.53)
                    if w_lit > 0.0:
                        lit_ch[r, c] = word[j]
                        alpha[r, c] = max(alpha[r, c], w_lit * f)
                        counts['lit'] += 1
                    if w_lit < 1.0:
                        dim_ch[r, c] = word[j]
                        cr, cg, cb = _hsv(DIM_HUE, DIM_SAT, v * (1.0 - w_lit) * f)
                        rgb[r, c, 0] = max(rgb[r, c, 0], cr)
                        rgb[r, c, 1] = max(rgb[r, c, 1], cg)
                        rgb[r, c, 2] = max(rgb[r, c, 2], cb)

    if S['prev'] is not None:
        age = t - S['prev'].get('fade_t0', t)
        if age >= DISSOLVE:
            S['prev'] = None
        else:
            fo = lambda stag: 1.0 - _smooth(max(0.0, age - stag) / (DISSOLVE * 0.45))
            draw(S['prev'], fo, 'c', 'paths', True)
            draw(S['prev'], fo, 'a', 'apaths', False)
    if S['cur'] is not None:
        age = t - S['cur']['t0']
        fi = lambda stag: _smooth((age - stag) / (DISSOLVE * 0.45))
        draw(S['cur'], fi, 'c', 'paths', True)
        draw(S['cur'], fi, 'a', 'apaths', False)

    counts['held'] = bool(held)
    counts['rings'] = len(S['rings'])
    counts['twinkle_on'] = bool(twinkle_on)
    counts['band_total'] = BAND * COLS
    S['stats'] = counts

    op(DIM_DAT).text = '\n'.join(''.join(row) for row in dim_ch)
    op(LIT_DAT).text = '\n'.join(''.join(row) for row in lit_ch)

    out = np.empty((VROWS, COLS, 4), np.float32)
    out[:, :, 0:3] = rgb
    out[:, :, 3] = alpha
    scriptOp.copyNumpyArray(np.ascontiguousarray(np.flipud(out)))
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS       # no input; must run every frame
