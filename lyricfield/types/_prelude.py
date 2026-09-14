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
