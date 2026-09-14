# Prepended to EVERY type's field.py by `VideoType.field_source`, because a
# field script is pushed into TouchDesigner as one DAT and cannot import a
# sibling module. This is the code all three renderers need and none of them
# should own.
#
# Keep it small and dependency-free: it runs before the field body, so numpy is
# not imported yet.

DRUM_DAT = 'drums'
DRUM_KINDS = ('kick', 'snare', 'hat')


def _read_drums():
    """When each drum is struck, by kind, from the table pushed in.

    This replaces evaluating the analysis CHOP per frame. Those channels were
    RMS *level* gates on two broad bands of the whole mix: a sustained bassline
    crosses the threshold and stays across it, so the events had no relation to
    the drums -- measured live, the phase of their rising edges within the beat
    was statistically uniform. These are onsets, found offline, identical in a
    preview and in a render.
    """
    out = {k: [] for k in DRUM_KINDS}
    try:
        d = op(DRUM_DAT)
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
            kind = d[r, 0].val.strip()
            if kind not in out:
                continue
            out[kind].append(float(d[r, 1].val.strip()))
        except (ValueError, IndexError, AttributeError):
            continue
    for k in out:
        out[k].sort()
    return out


def _struck(times, t, since):
    """Did a hit land in (since, t]?

    Half-open, so one strike fires exactly once however the frame rate moves.
    That is what lets the beatsync types drop their one-ring-per-beat-cell
    throttle, which was not edge detection at all -- it spawned a ring at the
    first frame a gate happened to be high inside a cell, dropping 17% of the
    kicks it was given and landing the rest up to 117 ms from the strike.
    """
    if not times or t <= since:
        return False
    lo, hi = 0, len(times)
    while lo < hi:                       # bisect_left, without the import
        mid = (lo + hi) // 2
        if times[mid] < since:
            lo = mid + 1
        else:
            hi = mid
    return lo < len(times) and since < times[lo] <= t


def _read_params(name='params'):
    """Every tunable this renderer was pushed, whichever way it was written.

    There were two writers and two readers and they did not match up.
    `lyricfield.sync` writes the DAT as a Python module (`P = {...}`), which is
    what the three grid renderers read through `mod()`; the eight renderers
    written since read `json.loads(dat.text)`, and `styles.capture_preview`
    wrote JSON. So a grid renderer previewed on its fallback defaults and a new
    renderer *rendered* on its fallback defaults, in both cases silently: a
    field script that cannot read its params does not fail, it just draws
    something plausible. Measured, a plain capture and a backdrop capture of
    `lyric_grid` came back byte-identical.

    One reader, accepting both, is what makes that impossible to have again.
    Returns `(values, missing)` -- `missing` is True when nothing could be read,
    which every renderer reports through its stats rather than swallowing.
    """
    try:
        d = op(name)
    except Exception:
        return {}, True
    if d is None:
        return {}, True
    # The module form first: it is what `sync` writes, so it is the common case,
    # and `mod()` caches the parse.
    try:
        p = dict(mod(name).P)
        if p:
            return p, False
    except Exception:
        pass
    try:
        txt = d.text
    except Exception:
        return {}, True
    if not (txt or '').strip():
        return {}, True
    try:
        import json
        p = json.loads(txt)
    except Exception:
        return {}, True
    return (p, False) if isinstance(p, dict) else ({}, True)
