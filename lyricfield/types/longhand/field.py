"""Longhand, inside TouchDesigner: lyrics lettered by hand over footage.

From frames of the Chainsmokers' "Closer" lyric video rather than descriptions
of it. Thick white marker lettering, flat and large, a lyric phrase at a time,
mixed caps and lowercase inside a single word, letters of different sizes, a
baseline that wanders.

Each frame this script works out which phrase is being sung, sets it into rows
that fit the frame, and writes one row per LETTER into a Specification DAT --
one DAT per letter size, because a Text TOP has a single font size for its
whole table. Nothing moves except the words changing.

Three things are worth knowing before changing any of it:

  * **The renderer phrases for itself.** Drawing one transcription line at a
    time is the obvious thing and it does not work: measured on a real song,
    121 cues fall into 12 lines of 3 to 32 words, the first spanning 11.4
    seconds. `_phrases` splits each line into near-equal parts instead. A gap
    threshold was tried first and orphans words -- 'Today' alone, 'across'
    alone.
  * **Every irregularity is a pure function of an index**, never of a random
    number or of the previous frame, so the same song letters the same way
    twice and a dropped frame or a seek changes nothing.
  * **The Spec DAT's origin is the LOWER LEFT**, and its rows are baselines
    here because the Text TOPs are bottom-aligned. Written top-down the whole
    block renders upside down, which reads as a broken renderer rather than an
    axis slip.
"""

CUE_DAT = 'lyrics'
PARAMS_DAT = 'params'
# One Specification DAT per letter size: spec0, spec1, ...
SPEC_STEM = 'spec'

DEFAULTS = {
    # `dim`, `hue`, `sat`, `lift`, `drift_secs`, `blur`, `ink`, `glow` and
    # `bloom` are not here: `build.py` bakes them into the plate and lettering
    # chains, and a key in DEFAULTS is a promise that this script reads it.
    'width': 720, 'height': 1280, 'size': 104.0,
    'center_x': 0.5, 'center_y': 0.47,
    'max_words': 5, 'max_chars': 26, 'max_seconds': 3.5,
    'wrap': 0.86, 'leading': 1.30, 'linger': 2.6,
    'steps': 3, 'spread': 0.11, 'waver': 0.055, 'jitter': 0.05,
    'shout': 0.34, 'tilt': 1.6,
    'kick_lift': 0.05, 'kick_time': 0.22,
    'intro_open': 0.35, 'arrive': 0.88, 'outro': 10.0,
    # measured facts, pushed with the params
    'kick_in': 0.0, 'high_in': 0.0, 'duration': 0.0, 'hold_windows': (),
    'offset': 0.0,
}

PARAMS_MISSING = False

S = {}

INTRO_RAMP = 2.0

SPEC_HEAD = 'x\ty\ttext'

# Roughly how wide a character is, in ems, for a marker face. Only used to set
# the line, so it does not have to be exact -- it has to be consistent, which a
# measured advance would not be across fonts.
EM = 0.56


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
    g['STEPS'] = max(1, int(g['STEPS']))
    g['MAX_WORDS'] = max(1, int(g['MAX_WORDS']))
    g['MAX_CHARS'] = max(4, int(g['MAX_CHARS']))
    dur = float(g['DURATION'] or 0.0)
    if dur <= 0.0:
        try:
            dur = float(root.time.end) / float(root.time.rate)
        except Exception:
            dur = 0.0
    g['TAIL_END'] = dur
    g['SIZES'] = _hand_sizes()
    S.pop('phrases', None)
    return P


def _hand_sizes():
    """The letter height each Text TOP is fixed at, smallest first.

    The same list `params.hand_sizes` computes, and it has to stay that way:
    `build.py` fixes each Text TOP's font size from that one and this script
    assigns letters from this one. If they drifted a letter would be drawn at a
    size the layout did not measure, and the line would not close up.
    """
    n = max(1, int(STEPS))
    if n == 1:
        return [float(SIZE)]
    lo = SIZE * (1.0 - SPREAD)
    step = (SIZE * (1.0 + SPREAD) - lo) / (n - 1)
    return [lo + step * i for i in range(n)]


try:
    _apply_params()
except Exception:
    for _k, _v in DEFAULTS.items():
        globals()[_k.upper()] = _v
    globals()['TAIL_END'] = 0.0
    globals()['SIZES'] = [92.56, 104.0, 115.44]


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
            line = 1
        if word:
            out.append((start, word, line))
    out.sort(key=lambda x: x[0])
    return out


def _phrases(cues):
    """The cues grouped into what goes on screen at once, computed once.

    Each transcription line is split into NEAR-EQUAL parts, enough of them that
    no part breaks the word, character or duration limits. Near-equal rather
    than greedy: a greedy split leaves a runt at the end of every line, and a
    gap threshold -- tried first -- orphans single words out of the middle.

    Breaks land mid-sentence, which is what the reference does too: "and play
    that / Blink-182 song", "that I KNOW / you CAN't / AFFORD".
    """
    import math

    if 'phrases' in S:
        return S['phrases']

    by_line = {}
    for c in cues:
        by_line.setdefault(c[2], []).append(c)

    out = []
    for _ln in sorted(by_line):
        cs = by_line[_ln]
        chars = sum(len(c[1]) + 1 for c in cs) - 1
        span = cs[-1][0] - cs[0][0]
        want = max(len(cs) / float(MAX_WORDS),
                   chars / float(MAX_CHARS),
                   span / max(1e-6, float(MAX_SECONDS)))
        n = max(1, int(math.ceil(want)))
        size = int(math.ceil(len(cs) / float(n)))
        for i in range(0, len(cs), size):
            out.append(cs[i:i + size])
    out.sort(key=lambda p: p[0][0])
    S['phrases'] = out
    return out


def _at(phrases, t):
    """Index of the last phrase begun at or before `t`, or -1."""
    lo, hi = 0, len(phrases)
    while lo < hi:
        mid = (lo + hi) // 2
        if phrases[mid][0][0] <= t:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


def _wobble(i, seed):
    """A repeatable -1..1 from an integer. Not a random number: the same letter
    of the same song has to land in the same place on every machine and on
    every re-render."""
    import math

    x = math.sin(i * 12.9898 + seed * 78.233) * 43758.5453
    return (x - math.floor(x)) * 2.0 - 1.0


def _shout(ch, i):
    """Whether this letter comes out capitalised.

    The reference mixes cases inside a single word -- "I CAN'4 Stop", "you
    CAN't AFFORD" -- and it is the most recognisable thing about the lettering.
    """
    if SHOUT <= 0.0:
        return ch
    return ch.upper() if (_wobble(i, 5.0) + 1.0) * 0.5 < SHOUT else ch


def _rows(words):
    """Break a phrase into rows that fit `wrap` of the frame width."""
    limit = max(1.0, WRAP * WIDTH)
    rows, cur = [], []
    for w in words:
        trial = cur + [w]
        wide = sum(len(x) + 1 for x in trial) - 1
        if cur and wide * SIZE * EM > limit:
            rows.append(cur)
            cur = [w]
        else:
            cur = trial
    if cur:
        rows.append(cur)
    return rows


def _spec(phrases, t, gain):
    """One Specification DAT body per letter size.

    PIXELS FROM THE LOWER LEFT, and each row's y is a BASELINE -- the Text TOPs
    are bottom-aligned so letters of different sizes sit on one line instead of
    on their own centres.
    """
    bodies = [[SPEC_HEAD] for _ in SIZES]
    if not phrases or gain <= 0.0:
        return ['\n'.join(b) for b in bodies], 0

    i = _at(phrases, t)
    if i < 0:
        return ['\n'.join(b) for b in bodies], 0
    phrase = phrases[i]
    # Gone if nothing followed it and it has been up too long. One gap in the
    # benchmark song is 15.4 seconds, and holding through that is a still.
    ends = (phrases[i + 1][0][0] if i + 1 < len(phrases)
            else phrase[-1][0] + LINGER)
    if t >= ends:
        return ['\n'.join(b) for b in bodies], 0

    rows = _rows([c[1] for c in phrase])
    step = SIZE * LEADING
    # The block is centred on `center_y`, and y counts up from the bottom.
    top = HEIGHT * (1.0 - CENTER_Y) + (len(rows) - 1) * step * 0.5
    drawn, k = 0, 0
    for r, words in enumerate(rows):
        text = ' '.join(words)
        # Laid out at the nominal size, so the row stays centred however the
        # letters are resized: the variation is a look, not a re-flow.
        wide = (len(text) - 1) * SIZE * EM if text else 0.0
        x = WIDTH * CENTER_X - wide * 0.5
        base = top - r * step
        for ch in text:
            if ch != ' ':
                pick = int((_wobble(k, 1.0) + 1.0) * 0.5 * len(SIZES))
                pick = max(0, min(len(SIZES) - 1, pick))
                dx = _wobble(k, 2.0) * JITTER * SIZE
                dy = _wobble(k, 3.0) * WAVER * SIZE
                bodies[pick].append('%d\t%d\t%s' % (
                    int(x + dx), int(base + dy), _shout(ch, k)))
                drawn += 1
            x += SIZE * EM
            k += 1
    return ['\n'.join(b) for b in bodies], drawn


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
        S['cues'] = _read_cues()

    phrases = _phrases(S.get('cues') or [])
    gain = _section_gain(t)

    if _held(t):
        bodies, drawn = [SPEC_HEAD for _ in SIZES], 0
    else:
        bodies, drawn = _spec(phrases, t, gain)
    for k, body in enumerate(bodies):
        try:
            d = op('%s%d' % (SPEC_STEM, k))
            if d is not None:
                d.text = body
        except Exception:
            pass

    # A hand does not rule a line, so the whole block sits a degree or two off.
    if TILT != 0.0:
        for k in range(len(SIZES)):
            _setpar('lh_text%d' % k, 'rotate', TILT)

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
    lift = KICK_LIFT * env * gain

    out = np.empty((16, 16, 4), np.float32)
    out[:, :, 0] = lift
    out[:, :, 1] = lift
    out[:, :, 2] = lift
    out[:, :, 3] = 1.0
    scriptOp.copyNumpyArray(np.ascontiguousarray(out))

    S['stats'] = {'drawn': drawn, 'cues': len(S.get('cues') or []),
                  'phrases': len(phrases), 'gain': round(gain, 3),
                  'params_missing': PARAMS_MISSING}
    return


def onGetCookLevel(scriptOp):
    return CookLevel.ALWAYS       # no input; must run every frame
