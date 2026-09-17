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
# The second bank, for the phrase that is still leaving. A Text TOP has one
# colour for its whole Specification DAT, so two phrases at two opacities need
# two sets of them -- the shape `monument` already uses for its ghost.
WAS_STEM = 'wasspec'

DEFAULTS = {
    # `dim`, `hue`, `sat`, `lift`, `drift_secs`, `blur`, `glow` and `bloom` are
    # not here: `build.py` bakes them into the plate and lettering chains, and a
    # key in DEFAULTS is a promise that this script reads it. `ink` IS here --
    # the outgoing phrase's brightness is set per frame against it.
    'width': 720, 'height': 1280, 'size': 112.0,
    'center_x': 0.5, 'center_y': 0.47,
    'max_words': 5, 'max_chars': 26, 'max_seconds': 3.5,
    'wrap': 0.86, 'leading': 1.30, 'linger': 2.6, 'indent': 0.04,
    'sway': 0.035, 'tremor': 0.012, 'whip': 0.30,
    'fade': 0.28, 'ghost': 0.45, 'place': 0.15,
    'steps': 3, 'spread': 0.11, 'waver': 0.055, 'jitter': 0.05,
    'shout': 0.34, 'tilt': 1.6, 'emphasis': 0.0,
    'ink': 0.97,
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

# How wide a character is, in ems, for a marker face. A single average is not
# good enough: the face is proportional, so spacing every letter by the mean
# leaves visible gaps around the narrow ones and the words come apart into
# letters -- measured on the first recording, "the quiet field" set as
# "THE QUi et  fi el d". A rough per-character table costs nothing and keeps
# words looking like words.
EM = 0.52
NARROW = "iljt!|.,;:'`"
WIDE = "MWmw@"


def _advance(ch):
    if ch in NARROW:
        return EM * 0.42
    if ch in WIDE:
        return EM * 1.34
    if ch == ' ':
        return EM * 0.62
    if ch.isupper():
        return EM * 1.12
    return EM


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
    g['INK_OF'] = float(g['INK'])
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
    globals()['SIZES'] = [99.68, 112.0, 124.32]
    globals()['INK_OF'] = 0.97


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


def _measure(text):
    """How wide a string sets, in pixels, at the nominal size."""
    return sum(_advance(c) for c in text) * SIZE


def _rows(words):
    """Break a phrase into rows that fit `wrap` of the frame width."""
    limit = max(1.0, WRAP * WIDTH)
    rows, cur = [], []
    for w in words:
        trial = cur + [w]
        wide = _measure(' '.join(trial))
        if cur and wide > limit:
            rows.append(cur)
            cur = [w]
        else:
            cur = trial
    if cur:
        rows.append(cur)
    return rows


def _span(phrases, i):
    """When phrase `i` lands and when it is done with the frame."""
    begins = phrases[i][0][0]
    ends = (phrases[i + 1][0][0] if i + 1 < len(phrases)
            else phrases[i][-1][0] + LINGER)
    return begins, ends


def _home(i):
    """Where phrase `i` is WRITTEN, in pixels from the frame's centre.

    The lettering never moves. The camera moves between these, which is the
    whole model: "as if all the words were filmed by an actual camera that was
    handheld and physically being moved from word to word".

    A pure function of the phrase's index, so consecutive phrases land in
    genuinely different parts of the sheet -- without that, a hand-over stacks
    the outgoing phrase directly behind the incoming one and the pair reads as
    mud.
    """
    # The SIGN alternates and the size is the wobble, rather than both coming
    # out of the hash. Left to the hash alone, consecutive phrases land on top
    # of each other whenever it happens to return two similar numbers -- and
    # then the camera has nowhere to travel, the hand-over stacks the outgoing
    # phrase behind the incoming one, and the pair reads as mud. Measured on
    # the shipped hash, phrases 3 and 4 were 0.04 of the frame apart.
    ax = 0.35 + 0.65 * abs(_wobble(i, 13.0))
    ay = 0.35 + 0.65 * abs(_wobble(i, 17.0))
    sx = 1.0 if i % 2 == 0 else -1.0
    sy = float(i % 3) - 1.0
    return sx * ax * PLACE * WIDTH, sy * ay * PLACE * HEIGHT * 0.5


def _settle(u):
    """0 to 1 across the whip, passing 1 and coming back.

    The damped spring `beat.impulse` uses, for the same reason: a camera swung
    onto a new phrase arrives slightly past it and settles. A linear move reads
    as a slide on a rail, which is what a lyric video does NOT look like.
    """
    import math

    if u <= 0.0:
        return 0.0
    if u >= 1.0:
        return 1.0
    return 1.0 - (1.0 - u) ** 2 * math.cos(math.pi * 2.0 * 0.62 * u)


# The two bands a hand moves in, as (hertz, weight, phase).
#
# These are not decoration; they are the measured signature. Tracking the
# reference's lettering at 25fps over 353 frame-to-frame steps: while holding,
# the median step is 2.09px on a 320-wide sample -- 0.65% of the frame width --
# and the direction REVERSES between consecutive frames 55% of the time in x
# and 40% in y.
#
# A drift never reverses. What reverses at that rate is energy near a third of
# the sample rate, which is why the tremor weights RISE with frequency: a
# sine's difference is a sine, so the derivative is dominated by the highest
# band, and reversals come from the derivative. Measured on these numbers at
# 25fps: median step 0.66% of the width, reversals 51% in x and 49% in y.
# Flat weights give 47/43 at a third of the magnitude; falling weights -- the
# obvious first draft -- give 27%, which is a drift with a wobble on it.
SWAY_BAND = ((0.113, 1.00, 0.0), (0.197, 0.62, 1.7), (0.311, 0.38, 3.9))
TREMOR_BAND = ((2.30, 0.35, 0.0), (3.70, 0.55, 2.3),
               (5.10, 0.85, 4.1), (6.90, 1.00, 5.6))


def _band(t, spec, seed):
    """A -1..1 pair from a sum of sines. x and y run at incommensurable rates,
    so the two axes never trace a diagonal line."""
    import math

    x = y = 0.0
    for f, a, ph in spec:
        x += a * math.sin(math.pi * 2.0 * f * t + ph + seed)
        y += a * math.sin(math.pi * 2.0 * f * t * 0.93 + ph * 1.7 + seed * 2.3)
    n = sum(a for _f, a, _p in spec) or 1.0
    return x / n, y / n


def _handheld(t):
    """What the hand is doing, in pixels. A pure function of the timestamp, so
    a dropped frame or a seek cannot change what is drawn."""
    sx, sy = _band(t, SWAY_BAND, 0.0)
    tx, ty = _band(t, TREMOR_BAND, 2.7)
    x = SWAY * WIDTH * sx + TREMOR * WIDTH * tx
    y = SWAY * WIDTH * sy + TREMOR * WIDTH * ty
    # Vertically a little tighter -- the reference reverses less often in y
    # (40% against 55%) and travels less far.
    return x, y * 0.8


def _camera(i, age, t):
    """Where the camera is looking, in sheet pixels, `age` into phrase `i`.

    It swings off the previous phrase onto this one over `whip` seconds, and
    breathes the whole time.
    """
    hx, hy = _home(i)
    px, py = _home(i - 1) if i > 0 else (hx, hy)
    e = _settle(age / WHIP) if WHIP > 0.0 else 1.0
    wx, wy = _handheld(t)
    return hx + (px - hx) * (1.0 - e) + wx, hy + (py - hy) * (1.0 - e) + wy


def _slide(j, i, age, t):
    """Where phrase `j` sits on screen while the camera is arriving at `i`.

    Both phrases of a hand-over are drawn through this, with the same camera --
    they are two things on one sheet being filmed by one hand. That is what
    makes the incoming phrase fly IN from the direction the camera came from
    while the outgoing one flies OUT the way it went, rather than the two of
    them crossfading where they stand.
    """
    cx, cy = _camera(i, age, t)
    hx, hy = _home(j)
    return hx - cx, hy - cy


def _hot_word(seed, count):
    """Which word of a phrase is picked out large, or -1 for none.

    Two of the references this renderer carries set one word of each phrase big
    and the rest of it small. A pure function of the phrase's index, like every
    other irregularity here.
    """
    if EMPHASIS <= 0.0 or count < 2:
        return -1
    k = int((_wobble(seed, 23.0) + 1.0) * 0.5 * count)
    return max(0, min(count - 1, k))


def _step_for(k, wi, hot):
    """Which size step a letter is drawn at.

    The hand's own scatter, and then `emphasis` pulls the picked word up
    towards the largest step and everything else down towards the smallest. At
    1 the phrase is one big word among small ones; at 0 nothing is picked out
    and this is the scatter alone.
    """
    top = len(SIZES) - 1
    pick = int((_wobble(k, 1.0) + 1.0) * 0.5 * len(SIZES))
    pick = max(0, min(top, pick))
    if EMPHASIS <= 0.0 or hot < 0 or top < 1:
        return pick
    want = top if wi == hot else 0
    return max(0, min(top, int(round(pick + (want - pick) * EMPHASIS))))


def _set(text, k, wi, hot):
    """One row, letter by letter: what is drawn, at what size, and how wide.

    Laid out on the size each letter is actually DRAWN at, not on the nominal
    one. The hand's own scatter is small enough either way, but `emphasis`
    picks a whole word out at the largest step -- and advancing that word on
    the nominal size runs it into the one after it.

    Returns the letters, the row's width in pixels, and where the letter and
    word counters have got to, because both run on across the rows of a phrase.
    """
    out, wide = [], 0.0
    for ch in text:
        shown = _shout(ch, k)
        if ch == ' ':
            wi += 1
            pick, size = None, SIZE
        else:
            pick = _step_for(k, wi, hot)
            size = SIZES[pick]
        adv = _advance(shown) * size
        out.append((shown, pick, adv))
        wide += adv
        k += 1
    return out, wide, k, wi


def _lay(bodies, phrase, off, k0=0, seed=0):
    """Write one phrase into `bodies`, at `off` -- where the camera puts it.

    PIXELS FROM THE LOWER LEFT, and each row's y is a BASELINE -- the Text TOPs
    are bottom-aligned so letters of different sizes sit on one line instead of
    on their own centres.
    """
    rows = _rows([c[1] for c in phrase])
    step = SIZE * LEADING
    sx, sy = off
    hot = _hot_word(seed, len(phrase))
    wi = 0
    # The block is centred on `center_y`, and y counts up from the bottom.
    top = HEIGHT * (1.0 - CENTER_Y) + (len(rows) - 1) * step * 0.5 + sy
    drawn, k = 0, k0
    for r, words in enumerate(rows):
        text = ' '.join(words)
        letters, wide, k, wi = _set(text, k, wi, hot)
        # Each row sits further right than the one above -- the reference
        # stacks them ragged, by hand, rather than centring them on each other.
        x = WIDTH * CENTER_X - wide * 0.5 + sx + r * INDENT * WIDTH
        # The frame is a hard edge. A row placed off-centre and then indented
        # can otherwise run out of it and lose its last word, which nothing
        # downstream would report -- the picture would simply be missing a word
        # and every check would pass.
        edge = SIZE * 0.12
        x = max(edge, min(x, WIDTH - edge - wide)) if wide < WIDTH - edge * 2 \
            else (WIDTH - wide) * 0.5
        base = top - r * step
        j = k - len(letters)
        for shown, pick, adv in letters:
            if pick is not None:
                dx = _wobble(j, 2.0) * JITTER * SIZE
                dy = _wobble(j, 3.0) * WAVER * SIZE
                bodies[pick].append('%d\t%d\t%s' % (
                    int(x + dx), int(base + dy), shown))
                drawn += 1
            x += adv
            j += 1
        # A row break stands in for the space that would have joined them.
        wi += 1
    return drawn


def _spec(phrases, t, gain):
    """What the two banks of Text TOPs should hold: the phrase arriving, and
    the one still leaving.

    They OVERLAP. For about a quarter of a second the outgoing phrase is still
    on screen, faded, drifting away, while the incoming one comes up underneath
    it -- which is what makes a hand-over rather than a cut, and the difference
    the whole renderer was missing.
    """
    now = [[SPEC_HEAD] for _ in SIZES]
    was = [[SPEC_HEAD] for _ in SIZES]
    out = lambda: (['\n'.join(b) for b in now], ['\n'.join(b) for b in was])

    if not phrases or gain <= 0.0:
        return out() + (0, 0.0)

    i = _at(phrases, t)
    if i < 0:
        return out() + (0, 0.0)

    begins, ends = _span(phrases, i)
    if t >= ends:
        return out() + (0, 0.0)
    age = t - begins
    drawn = _lay(now, phrases[i], _slide(i, i, age, t), seed=i)

    # ... and the one before it, while it is still leaving.
    ghost = 0.0
    if i > 0 and FADE > 0.0:
        gone = age / FADE
        if gone < 1.0:
            # The SAME camera, so the outgoing phrase is carried off the edge by
            # the move that brought the new one in rather than fading where it
            # stands. "The words fly in and out of the screen."
            _lay(was, phrases[i - 1], _slide(i - 1, i, age, t), k0=997,
                 seed=i - 1)
            ghost = GHOST * (1.0 - _smooth(gone))
    return out() + (drawn, ghost)


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
        blank = [SPEC_HEAD for _ in SIZES]
        now, was, drawn, ghost = blank, blank, 0, 0.0
    else:
        now, was, drawn, ghost = _spec(phrases, t, gain)
    for k, body in enumerate(now):
        try:
            d = op('%s%d' % (SPEC_STEM, k))
            if d is not None:
                d.text = body
        except Exception:
            pass
    for k, body in enumerate(was):
        try:
            d = op('%s%d' % (WAS_STEM, k))
            if d is not None:
                d.text = body
        except Exception:
            pass
    # How faint the outgoing phrase is. One Text TOP has one colour for its
    # whole table, which is why there are two banks rather than one.
    _setpar('lh_ghost', 'brightness1', ghost * INK_OF)

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
