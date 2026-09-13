"""The field script's layout and timeline logic.

`field.py` runs inside TouchDesigner but imports standalone, so the part that
decides *which words are on screen and when* is testable with no TD at all.

Every invariant here was verified by hand while chasing "the lyrics are not
highlighted", and every one of them corresponds to a bug that shipped:

  * overlapping windows handed a stanza over 2.65s before its first word, so the
    last line of every stanza was sung while dissolving out;
  * holes between windows drew nothing, so instrumental gaps were black;
  * a stanza whose lines would not fit the grid silently dropped them, so the
    words were sung with nothing on screen to light.
"""

from __future__ import annotations

import numpy as np
import pytest


def cues(*triples):
    return list(triples)


def stanzas_for(mod, triples, duration):
    mod.TAIL_END = duration
    lines = mod._lines(list(triples))
    return lines, mod._stanzas(lines)


def ordered(stanzas):
    return sorted(stanzas.values(), key=lambda i: i["start"])


def owner_of(order, t):
    """The stanza on screen at `t`: the latest window that has opened."""
    found = None
    for info in order:
        if info["start"] <= t:
            found = info
        else:
            break
    return found


# ------------------------------------------------------------ the envelope

def test_lit_weight_is_zero_before_the_cue(field_mod):
    assert field_mod._lit_weight(0.9, 1.0) == 0.0


def test_lit_weight_holds_at_full_then_falls(field_mod):
    m = field_mod
    peak = 1.0 + m.RAMP_UP + m.HOLD / 2
    assert m._lit_weight(peak, 1.0) == 1.0
    gone = 1.0 + m.RAMP_UP + m.HOLD + m.RAMP_DN + 0.01
    assert m._lit_weight(gone, 1.0) == 0.0


def test_lit_weight_never_leaves_zero_to_one(field_mod):
    m = field_mod
    for t in np.arange(0.0, 4.0, 0.01):
        assert 0.0 <= m._lit_weight(float(t), 1.0) <= 1.0


# ------------------------------------------------------- the stanza timeline

SONG = [("never", 1.0, 1), ("mine", 1.6, 1),
        ("again", 6.0, 2), ("tonight", 6.7, 2),
        ("and", 30.0, 3), ("after", 30.8, 3)]


def test_every_instant_belongs_to_exactly_one_stanza(field_mod):
    _, st = stanzas_for(field_mod, SONG, 60.0)
    order = ordered(st)
    assert order[0]["start"] <= 0.0, "the field must be composed from the first frame"
    starts = [i["start"] for i in order]
    assert starts == sorted(starts)
    assert len(set(starts)) == len(starts), "two stanzas may not open at the same instant"
    for t in np.arange(0.0, 60.0, 0.25):
        assert owner_of(order, float(t)) is not None, f"nothing owns t={t}"


def test_no_cue_falls_inside_an_ambient_window(field_mod):
    """Ambient windows are drawn with lighting disabled, so a cue inside one
    is a word that can never light."""
    _, st = stanzas_for(field_mod, SONG, 60.0)
    order = ordered(st)
    for _w, t, _ln in SONG:
        assert not owner_of(order, t)["ambient"], f"cue at {t} landed in an ambient window"


def test_no_cue_precedes_its_own_stanza(field_mod):
    lines, st = stanzas_for(field_mod, SONG, 60.0)
    for info in st.values():
        if info["ambient"]:
            continue
        for ln in info["lines"]:
            for _w, t in lines[ln]:
                assert t >= info["start"] - 1e-9


def test_a_stanza_still_owns_the_screen_while_it_sings(field_mod):
    """The handover must not happen before the outgoing stanza's last word.

    This is the bug that made the last line of every stanza dissolve while it
    was being sung.
    """
    lines, st = stanzas_for(field_mod, SONG, 60.0)
    order = ordered(st)
    for k, info in enumerate(order[:-1]):
        if info["ambient"]:
            continue
        nxt = order[k + 1]["start"]
        for ln in info["lines"]:
            for _w, t in lines[ln]:
                assert t < nxt, f"cue at {t} is sung after its stanza handed over"


def test_gaps_are_filled_rather_than_left_black(field_mod):
    """A 24-second hole between lyrics must be covered by ambient windows."""
    _, st = stanzas_for(field_mod, SONG, 60.0)
    order = ordered(st)
    assert any(i["ambient"] for i in order), "a long instrumental gap drew nothing"
    for t in np.arange(8.0, 29.0, 0.5):
        assert owner_of(order, float(t)) is not None


# ------------------------------------------------------------- edge cases

def test_an_instrumental_does_not_crash(field_mod):
    """No cues at all. The renderer must still tile the timeline."""
    _, st = stanzas_for(field_mod, [], 120.0)
    assert st, "an instrumental produced no stanzas at all"
    assert all(i["ambient"] for i in st.values())
    assert ordered(st)[0]["start"] <= 0.0


def test_a_one_word_song(field_mod):
    _, st = stanzas_for(field_mod, [("hi", 5.0, 1)], 60.0)
    assert st
    assert ordered(st)[0]["start"] <= 0.0


def test_a_track_shorter_than_one_ambient_tile(field_mod):
    _, st = stanzas_for(field_mod, [("hi", 1.0, 1)], 3.0)
    assert len(st) >= 1
    assert ordered(st)[0]["start"] <= 0.0


# ----------------------------------------------------------------- layout

def test_a_long_line_is_split_to_something_the_grid_can_hold(field_mod):
    """Transcription hands back whole verses as one segment.

    One song produced a 27-word line needing 267 cells of a grid whose longest
    path reaches about 264; it failed to place every time, and a line that never
    places has no cells, so its words were sung with nothing to light.
    """
    m = field_mod
    long_line = [(f"word{i}", float(i)) for i in range(40)]
    out = m._split_long({1: long_line})
    assert len(out) > 1, "an over-long line was not split"
    for words in out.values():
        span = sum(2 * len(w) - 1 for w, _ in words) + (m.GAP_MAX + 1) * (len(words) - 1)
        assert span <= m.LINE_SPAN, "a chunk still exceeds what a path can reach"
    assert [w for words in out.values() for w, _ in words] == [w for w, _ in long_line]


def test_split_preserves_order_and_times(field_mod):
    m = field_mod
    src = {1: [("a", 1.0), ("b", 2.0)], 2: [("c", 3.0)]}
    out = m._split_long(src)
    flat = [(w, t) for _k in sorted(out) for w, t in out[_k]]
    assert flat == [("a", 1.0), ("b", 2.0), ("c", 3.0)]


def test_no_stanza_line_is_dropped(field_mod):
    """Every line a stanza claims must actually be placed on the grid.

    A line that fails to lay out used to fall through to the decoration pool,
    which is drawn with lighting disabled -- present, dim, and permanently
    unable to light.
    """
    m = field_mod
    song = []
    t = 1.0
    for ln in range(1, 11):
        for w in ("holding", "on", "to", "the", "quiet", "part"):
            song.append((w, t, ln))
            t += 0.4
        t += 1.0
    lines, st = stanzas_for(m, song, 120.0)
    m.S["lines"] = lines
    m.S["stanzas"] = st
    for si, info in st.items():
        if info["ambient"]:
            continue
        built = m._build(si, 0.0, np.random.default_rng(si + 11))
        missing = [ln for ln in info["lines"] if ln not in built["paths"]]
        assert not missing, f"stanza {si} dropped lines {missing}"


def test_laid_cells_stay_inside_the_band(field_mod):
    """`band` rows inside `vrows`; letters outside it are the failure that
    shipped three times as dead black at the bottom of frame."""
    m = field_mod
    rng = np.random.default_rng(3)
    got = m._lay_line([("holding", 0.0), ("on", 1.0)], set(), rng)
    assert got is not None
    for cells in got.values():
        for r, c in cells:
            assert m.BAND_TOP <= r < m.BAND_TOP + m.BAND
            assert 0 <= c < m.COLS


def test_a_line_never_overlaps_itself(field_mod):
    m = field_mod
    rng = np.random.default_rng(5)
    got = m._lay_line([("holding", 0.0), ("onto", 1.0), ("this", 2.0)], set(), rng)
    assert got is not None
    cells = [cell for v in got.values() for cell in v]
    assert len(cells) == len(set(cells))


def test_claimed_cells_are_respected(field_mod):
    """Two lines must never be laid on top of each other."""
    m = field_mod
    rng = np.random.default_rng(7)
    first = m._lay_line([("holding", 0.0)], set(), rng)
    assert first is not None
    claimed = {cell for v in first.values() for cell in v}
    second = m._lay_line([("onto", 0.0)], claimed, rng)
    if second is not None:
        assert not claimed & {cell for v in second.values() for cell in v}


# -------------------------------------------------------- the params fallback

def test_the_fallback_defaults_are_not_a_song(field_mod):
    """They used to be the benchmark track's own measurements.

    A malformed params DAT therefore produced a coherent, non-black, entirely
    plausible video tuned to a different song, with nothing on either side
    noticing. A fallback that is convincingly wrong is worse than one that is
    obviously wrong.
    """
    d = field_mod.DEFAULTS
    assert d["kick_in"] == 0.0
    assert d["high_in"] == 0.0
    assert d["beat_anchor"] == 0.0
    assert d["duration"] == 0.0, "a fallback duration is some other song's length"
    assert not d["hold_windows"], "a fallback must not carry another song's splices"


def test_a_missing_params_dat_is_recorded_not_swallowed(field_mod):
    """Outside TouchDesigner `mod()` does not exist, which is exactly the
    failure the flag is for."""
    field_mod._load_params()
    assert field_mod.PARAMS_MISSING is True


def test_beat_period_is_never_zero(field_mod):
    """`int(floor((t - anchor) / period))` is evaluated every frame in a
    CookLevel.ALWAYS TOP; a zero period is an OverflowError at 60fps."""
    assert field_mod.DEFAULTS["beat_period"] > 0
