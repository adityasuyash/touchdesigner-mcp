# Runs INSIDE TouchDesigner as the Script TOP callbacks. Not importable standalone:
# it depends on TD globals (op, root, me) and is synced into the .toe by
# lyricfield.sync. Edit it here, in the repo -- never in the DAT.
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

# Every tunable below is read from the params DAT that lyricfield.sync writes,
# falling back to the value here when a key is absent. The fallbacks are a
# working configuration, not placeholders -- they are what this renderer does
# with no config at all.
#
# Params are re-read whenever that DAT's text changes rather than at import,
# because pushing a value must take effect on the next cook: TouchDesigner does
# not reliably re-import a callbacks DAT whose text did not itself change, so
# binding at import time made every look change a silent no-op.
DEFAULTS = {
    # grid
    'cols': 24, 'vrows': 24, 'band': 22, 'band_top': 1,
    'letter_frac': 0.28,
    # look
    'dim_hue': 0.58, 'dim_sat': 0.35,
    'level_min': 0.10, 'level_max': 0.38, 'ceil': 0.58,
    'drift_min': 3.0, 'drift_max': 6.0, 'dissolve': 2.5,
    # cueing
    'ramp_up': 0.12, 'hold': 0.80, 'ramp_dn': 0.25, 'lead': 0.15,
    'offset': 0.0, 'stanza_size': 5,
    'ambient_target': 190, 'ambient_cycle': 6.0,
    'gap_min': 2, 'gap_max': 4,
    # beat
    'ripple_time': 0.55, 'ripple_sigma': 2.2, 'ripple_lift': 0.14,
    'spark_time': 0.25, 'spark_peak': 0.52, 'spark_frac': 0.055,
    'twinkle_frac_lo': 0.04, 'twinkle_frac_hi': 0.11,
    'twinkle_decay': 0.22, 'twinkle_lift': 0.20,
    # Track structure, measured per song by lyricfield.analysis and pushed in.
    #
    # These are NOT a song. They used to be one -- the 90-second benchmark
    # track's own measurements, down to its three splice points -- which meant
    # that if the params DAT ever failed to parse, the field rendered a
    # coherent, non-black, entirely plausible video tuned to a different song,
    # and nothing on either side noticed. A fallback that produces a convincing
    # wrong answer is worse than one that produces an obviously wrong one.
    #
    # So: neutral. No kick, no splices, a nominal tempo, and a duration of zero
    # that `_apply_params` treats as "unknown" rather than as a length.
    'kick_in': 0.0, 'beat_anchor': 0.0, 'beat_period': 0.5,
    'high_in': 0.0,
    'hold_windows': (),
    'duration': 0.0,
}

# Set when the params DAT could not be read, so the renderer can say so rather
# than quietly running on fallbacks. Read by onCook.
PARAMS_MISSING = False

# Operator names as they exist in the project (relative to /project1).
CUE_DAT = 'lyrics'
PARAMS_DAT = 'params'
DIM_DAT = 'v7_chars_dim'
LIT_DAT = 'v7_chars_lit'
ANALYSIS_CHOP = 'v6_aa'

S = {}


def _params_text():
    """The params DAT's raw text, used as a change key. Cheap; runs every cook."""
    d = op(PARAMS_DAT)
    return d.text if d is not None else ''


def _load_params():
    """Params live in a sibling Text DAT written by lyricfield.sync. A plain
    `import` cannot see a DAT -- TD exposes them through mod() instead.

    A failure here is recorded rather than swallowed. Falling back silently is
    how a malformed params DAT turned into a plausible video of the wrong song.
    """
    global PARAMS_MISSING
    try:
        p = dict(mod(PARAMS_DAT).P)
        PARAMS_MISSING = not p
        return p
    except Exception:
        PARAMS_MISSING = True
        return {}


def _apply_params():
    """Bind every tunable as a module global, config over fallback.

    The grid dimensions are ints because they index numpy arrays, and TOML
    happily round-trips them as floats.
    """
    P = _load_params()
    g = globals()
    for key, fallback in DEFAULTS.items():
        g[key.upper()] = P.get(key, fallback)
    for key in ('cols', 'vrows', 'band', 'band_top', 'stanza_size',
                'ambient_target', 'gap_min', 'gap_max'):
        g[key.upper()] = int(g[key.upper()])
    # The ambient tail has to cover the whole timeline, which runs past the last
    # cue. Anchoring it to the measured duration is what stops the grid emptying
    # partway through a song longer than the old baked-in 91s.
    # A duration of zero means "not measured yet", not "a zero-length song".
    # Without a real one the ambient tail has nothing to tile against, so fall
    # back to the timeline itself rather than to some other song's length.
    dur = float(P.get('duration') or 0.0)
    if dur <= 0.0:
        try:
            dur = float(root.time.end) / float(root.time.rate)
        except Exception:
            dur = 0.0
    g['TAIL_END'] = dur
    # Derived, not tunable: how long the outgoing stanza is kept alive. Its
    # cells are invisible once the fade completes, but a word cued right at the
    # handover still has to be able to light through its whole envelope, and a
    # short dissolve against a long hold makes the cue outlive the fade. At the
    # defaults DISSOLVE already wins; the Motion and Word-timing controls can
    # invert that, and this keeps the guarantee rather than warning about it.
    g['PREV_LIFE'] = max(float(g['DISSOLVE']),
                         float(g['RAMP_UP']) + float(g['HOLD']) + float(g['RAMP_DN']))
    # The crossfade divides by this. `dissolve` may legitimately be set to 0,
    # which would raise inside a CookLevel.ALWAYS Script TOP -- an exception
    # every frame, in the one place nothing is watching.
    g['FADE_SPAN'] = max(1e-6, float(g['DISSOLVE']) * 0.45)
    # How many letters one stanza may ask the grid for. Letters sit on every
    # other cell along a path, so the ceiling is about half the band's cells --
    # and paths have to be contiguous, which costs more again, so the working
    # figure is a fraction of that rather than the ceiling. Calibrated by
    # counting lines that failed to place across two songs.
    g['LETTER_BUDGET'] = int(BAND * COLS * LETTER_FRAC)
    # The most cells one line's path may need. A horizontal path skips a row on
    # each wrap, so it can reach about half the band's rows -- and it starts at
    # a random cell, so on average far less is ahead of it. Derived, not
    # tunable: it is a fact about the grid, not a preference.
    g['LINE_SPAN'] = max(8, int((BAND // 2) * COLS * 0.75))
    return P


_apply_params()


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
        # Only row 0 can be the header; matching 'word' on every row dropped
        # that cue from any song that happens to sing it.
        if not w or (r == 0 and w.lower() == 'word'):
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
    return _split_long(d)


def _split_long(d):
    """Break a line that cannot physically fit the grid into ones that can.

    Transcription decides where a line ends, and it sometimes hands back a whole
    verse as a single segment -- one song had a 27-word, 108-letter "line"
    needing 267 cells of a grid whose longest wrapping path reaches about 264.
    `_lay_line` then failed on it every time, and a line that never places has
    no cells, so its words were sung with nothing on screen to light. A quarter
    of that song's stanzas lost a line this way.

    Splitting is the renderer's business rather than the cue table's: the cue
    table is the user's, hand-editable, and knows nothing about grid geometry.
    Sub-lines are numbered `ln * 100 + k` so ordering and uniqueness hold.
    """
    out = {}
    for ln in sorted(d):
        chunk, span, k = [], 0, 0
        for w, t in d[ln]:
            # A single word longer than a whole path can never be laid, and
            # appending it anyway reintroduces exactly the failure this function
            # exists to prevent, one level down. Clip it instead: a visibly
            # truncated word beats a line that silently never appears.
            if 2 * len(w) - 1 > LINE_SPAN:
                w = w[: max(1, (LINE_SPAN + 1) // 2)]
            need = (2 * len(w) - 1) + (GAP_MAX + 1 if chunk else 0)
            if chunk and span + need > LINE_SPAN:
                out[ln * 100 + k] = chunk
                k += 1
                chunk, span, need = [], 0, 2 * len(w) - 1
            chunk.append((w, t))
            span += need
        if chunk:
            out[ln * 100 + k] = chunk
    return out


def _stanzas(lines):
    """One contiguous timeline: every instant belongs to exactly one stanza.

    Windows used to be derived per group, free to overlap or to leave holes,
    and both did damage.

    Overlap handed over early. The next stanza's window opened LEAD + DISSOLVE
    (2.65s) before its first word, which is while the current stanza is still
    singing its last line -- so those words dissolved out while being sung. The
    stagger is per letter, so some letters of a word survived and others did
    not, which read as a glitch rather than as a timing bug. It affected the
    last line of every stanza in every song.

    A hole was simply black. Outside every window there is no current stanza
    and the grid is spaces; ambient stanzas were only tiled after the last
    lyric. One song measured 16% of a 30s render as pure black, including a
    4.3s run over an instrumental break.

    So a boundary is placed, not derived. It is never later than the incoming
    stanza's first word -- past that the word has nothing to light -- and
    otherwise as late as possible, which is the outgoing stanza's last cue
    envelope, so a stanza always sings its last line while it is still the
    current one. Holes wide enough to be worth a layout of their own become
    ambient stanzas; shorter ones stay with the stanza before them rather than
    recomposing the whole field for three seconds.

    `end` survives as *when this stanza stops singing* -- the input to the next
    boundary, and a diagnostic. It is no longer the window's right edge; the
    window runs until the next stanza's `start`.
    """
    # Group by what fits on the grid, not by a fixed count of lines.
    #
    # STANZA_SIZE lines of whatever length the transcription happened to produce
    # routinely asked for more cells than exist. One stanza wanted 244 letters --
    # about 488 of the grid's 528 cells once the blank between letters is counted
    # -- and `_lay_line` simply failed on the lines it could not place. Those
    # lines then had no cells at all, so the words were sung and nothing lit,
    # which is most of what "the lyrics are not highlighted" turned out to be.
    #
    # STANZA_SIZE stays as the upper bound on lines; the letter budget is what
    # actually binds. A single line longer than the budget still gets its own
    # stanza rather than being dropped.
    # Ordered by when each line is *sung*, not by its number.
    #
    # Line numbers come from transcription segments, and overlapping segments
    # produce numbers that do not ascend with time. The boundary walk below
    # assumes they do: a stanza whose first cue precedes the previous stanza's
    # gets a window that opens in the past, and since selection is "the latest
    # window that has opened", such a stanza is permanently shadowed -- its
    # words are sung with nothing on screen lit. That is the original complaint
    # arriving by a different route.
    keys = sorted(lines, key=lambda ln: (min(t for _w, t in lines[ln]), ln))
    budget = max(1, int(LETTER_BUDGET))
    grps, i = [], 0
    while i < len(keys):
        grp, letters = [], 0
        while i < len(keys) and len(grp) < STANZA_SIZE:
            n = sum(len(w) for w, _ in lines[keys[i]])
            if grp and letters + n > budget:
                break
            grp.append(keys[i]); letters += n; i += 1
        ts = [t for ln in grp for _, t in lines[ln]]
        grps.append((grp, min(ts), max(ts) + RAMP_UP + HOLD + RAMP_DN))

    out, n, cursor = {}, 0, 0.0

    def fill(a, b):
        """Tile [a, b) with ambient stanzas, or leave it to the caller when it
        is too short to be worth one. AMBIENT_CYCLE is the smallest hole worth
        its own layout; segments are equal rather than a fixed cycle plus a
        remainder, because a remainder shorter than the crossfade would never
        finish fading in before it was replaced."""
        nonlocal n
        k = int((b - a) // AMBIENT_CYCLE)
        if k < 1:
            return a
        step = (b - a) / k
        for i in range(k):
            out[n] = {'lines': [], 'start': a + i * step,
                      'end': a + (i + 1) * step, 'ambient': True, 'rot': n}
            n += 1
        return b

    for grp, sing0, sing_end in grps:
        want = sing0 - LEAD - DISSOLVE          # the run-up the crossfade wants
        cursor = fill(cursor, want)
        # never past the first word, never before the previous stanza is done
        out[n] = {'lines': grp, 'start': min(sing0, max(cursor, want)),
                  'end': sing_end, 'ambient': False, 'rot': n}
        n += 1
        cursor = sing_end
    fill(cursor, TAIL_END)
    # The song may open sooner than one ambient tile, leaving a few seconds at
    # the front belonging to nothing. Give them to whatever comes first: the
    # field should be present through a short intro, fading in, rather than
    # black until the first window opens.
    if out:
        first = min(out, key=lambda si: out[si]['start'])
        out[first]['start'] = min(0.0, out[first]['start'])
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
    for a, b in HOLD_WINDOWS:
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


def _lay_line(words, claimed, rng, tries=600):
    """One continuous path per line: words intact, one blank cell between letters,
    GAP_MIN..GAP_MAX between words, blank row skipped on each wrap. Horizontal
    (left-to-right) or vertical (top-to-bottom) only -- never diagonal or reversed.

    A path that runs off the end of the band wraps back to the start of it rather
    than failing. It used to fail, and that quietly biased the whole layout
    upwards: a start row is picked at random, but a long line only fits if it
    starts high, so every long line that placed had placed near the top and the
    bottom of the frame was left empty. Wrapping lets a line start anywhere, and
    the cell-collision check below is what still rejects a path that would
    overlap itself.
    """
    def _wrap(rr, cc):
        return (BAND_TOP + (rr - BAND_TOP) % BAND, cc % COLS)

    for _ in range(tries):
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
            r, c = _wrap(r, c)
            cells, rr, cc, step = [], r, c, 0
            for _i in range(span):
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
                rr, cc = _wrap(rr, cc)
            if len(cells) != len(w) or any(x in claimed or x in used for x in cells):
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
            r, c = _wrap(r, c)
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
            # Three times the budget a decoration line gets: a stanza line that
            # fails to place costs the song a word it sings, a decoration line
            # that fails costs nothing. This runs once per stanza, not per frame.
            got = _lay_line(S['lines'][ln], claimed, rng, tries=1800)
            if got:
                paths[ln] = got
                for cl in got.values():
                    claimed.update(cl); letters += len(cl)
    # A stanza line that still failed is NOT decoration material. Letting it
    # fall through to the pool laid it as decoration, and decoration is drawn
    # with allow_lit=False -- so the line sat on screen permanently unable to
    # light, a word the song sings and the field ignores. Absent is better than
    # present-and-wrong.
    own = set(info['lines'])
    pool = [ln for ln in sorted(S['lines'])
            if ln not in paths and ln not in own]
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
    """Declare the Script TOP's custom parameters.

    `Cueoffset` is the live nudge you reach for while watching playback, and
    onCook reads it every frame. Declaring it here is what keeps it in the repo:
    it was added by hand in the TD UI once, which meant a network built from
    scratch came up without it and a push had nothing to write to.

    Appending is guarded because this callback also runs when the DAT is merely
    reassigned, and TouchDesigner raises on a duplicate parameter name.
    """
    try:
        if hasattr(scriptOp.par, 'Cueoffset'):
            return
        page = scriptOp.appendCustomPage('Field')
        pg = page.appendFloat('Cueoffset', label='Cue Offset (s)')
        par = pg[0]
        par.default = 0.0
        par.normMin, par.normMax = -5.0, 5.0
        par.val = 0.0
    except Exception:
        # A missing par is survivable -- onCook falls back to the pushed OFFSET.
        pass
    return


def onPulse(par):
    return


def onCook(scriptOp):
    # A pushed param changes the grid geometry and the cached layout, so a
    # params change rebuilds exactly like a cue-table change does.
    pkey = _params_text()
    if 'rng' not in S or S.get('key') != op(CUE_DAT).text or S.get('pkey') != pkey:
        _apply_params()
        _init()
        S['pkey'] = pkey

    t = root.time.seconds
    prev_t = S['last_t']
    if prev_t < 0 or t < prev_t:            # first cook or a backward scrub
        S['stanza'] = None; S['cur'] = None; S['prev'] = None
        S['levels'] = {}; S['rings'] = []
        S['spark_t'] = np.full((VROWS, COLS), -1.0e9, np.float32)
        S['twinkle'] = set(); S['twinkle_t'] = None
        S['beat_i'] = -1; S['hold_anchor'] = None
    S['last_t'] = t
    try:
        off = float(scriptOp.par.Cueoffset.eval())
    except Exception:
        off = float(OFFSET)
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

    kick_in = KICK_IN
    twinkle_on = (t < kick_in) and not held
    if twinkle_on:
        anchor = BEAT_ANCHOR
        period = BEAT_PERIOD
        bi = int(np.floor((t - anchor) / period))
        if bi != S['beat_i']:
            S['beat_i'] = bi
            frac = TWINKLE_FRAC_LO if t < HIGH_IN else \
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

    # ---- stanza selection: the latest window that has opened, full stop ----
    # The windows tile the timeline, so "latest start that is not in the future"
    # names exactly one stanza and there is nothing to fall between. Testing
    # `end` as well is what produced a black screen in every lyric gap: no
    # window contained t, so there was no current stanza and the grid was
    # spaces. It also emptied the grid past the song's duration; now the last
    # stanza holds instead.
    cur_si, best = None, -1e9
    for si, info in S['stanzas'].items():
        s0 = info['start'] + off
        if s0 <= t and s0 > best:
            best, cur_si = s0, si
    if cur_si is None and S['stanzas']:
        # only reachable before the first window -- a positive cue offset pushes
        # every start past zero -- where holding the opening stanza beats nothing
        cur_si = min(S['stanzas'], key=lambda si: S['stanzas'][si]['start'])
    if cur_si != S['stanza']:
        S['prev'] = S['cur'] if S['cur'] is not None else None
        if S['prev'] is not None:
            S['prev']['fade_t0'] = t
        S['stanza'] = cur_si
        S['levels'] = {}
        if cur_si is None:
            S['cur'] = None
        else:
            # Anchor the fade-in to the window, not to the frame that noticed
            # it. Building at `t` restarts the crossfade whenever a stanza is
            # entered late -- which is every preview, since previews park
            # mid-song deliberately -- and the draw loop skips a cell until it
            # has faded in, so the first couple of seconds never lit.
            w0 = S['stanzas'][cur_si]['start'] + off
            S['cur'] = _build(cur_si, min(t, w0), rng)

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
                    # A word is lit because the song is singing it, not because
                    # its cell happens to have finished dissolving in. Gating
                    # the lit layer on the crossfade is what made the last line
                    # of every stanza light partially or not at all: by then the
                    # stanza was the outgoing one and fading, so the fade factor
                    # was near zero for exactly the letters being sung.
                    #
                    # In the healthy case this is a no-op -- a stanza entered at
                    # its window start has fully faded in by its first cue, so
                    # the factor is 1.0 and nothing changes. It alters the
                    # output only in the situations it exists to fix.
                    if w_lit > 0.0:
                        lit_ch[r, c] = word[j]
                        alpha[r, c] = max(alpha[r, c], w_lit)
                        counts['lit'] += 1
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
                    if w_lit < 1.0:
                        dim_ch[r, c] = word[j]
                        cr, cg, cb = _hsv(DIM_HUE, DIM_SAT, v * (1.0 - w_lit) * f)
                        rgb[r, c, 0] = max(rgb[r, c, 0], cr)
                        rgb[r, c, 1] = max(rgb[r, c, 1], cg)
                        rgb[r, c, 2] = max(rgb[r, c, 2], cb)

    if S['prev'] is not None:
        age = t - S['prev'].get('fade_t0', t)
        if age >= PREV_LIFE:
            S['prev'] = None
        else:
            fo = lambda stag: 1.0 - _smooth(max(0.0, age - stag) / FADE_SPAN)
            draw(S['prev'], fo, 'c', 'paths', True)
            draw(S['prev'], fo, 'a', 'apaths', False)
    if S['cur'] is not None:
        age = t - S['cur']['t0']
        fi = lambda stag: _smooth((age - stag) / FADE_SPAN)
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
