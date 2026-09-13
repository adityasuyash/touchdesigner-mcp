"""The cue table: the one piece of user data the whole system is built around."""

from __future__ import annotations

import pytest

from lyricfield.cues import Cue, CueTable, cues_from_lines


def table(*triples) -> CueTable:
    return CueTable([Cue(w, t, ln) for w, t, ln in triples])


# ------------------------------------------------------------- round trips

def test_tsv_round_trip(tmp_path):
    t = table(("hold", 1.0, 1), ("on", 1.5, 1), ("tight", 2.25, 2))
    p = tmp_path / "cues.tsv"
    t.save(p)
    back = CueTable.load(p)
    assert [(c.word, c.start, c.line) for c in back.cues] == \
           [(c.word, c.start, c.line) for c in t.cues]


def test_dat_text_round_trip():
    t = table(("a", 0.5, 1), ("b", 1.0, 2))
    assert [(c.word, c.start, c.line) for c in CueTable.from_dat_text(t.to_dat_text()).cues] \
        == [("a", 0.5, 1), ("b", 1.0, 2)]


def test_a_song_may_sing_the_word_word(tmp_path):
    """Only row 0 can be the header.

    Matching 'word' on every row dropped that cue from any song that happens to
    sing it -- a real bug, and one no amount of staring at a video would explain.
    """
    p = tmp_path / "cues.tsv"
    p.write_text("word\tstart_seconds\tline\nword\t1.00\t1\nup\t1.50\t1\n")
    got = CueTable.load(p)
    assert [c.word for c in got.cues] == ["word", "up"]


def test_load_of_a_missing_file_is_empty(tmp_path):
    assert CueTable.load(tmp_path / "nope.tsv").cues == []


def test_comments_are_skipped(tmp_path):
    p = tmp_path / "c.tsv"
    p.write_text("# a note\nword\tstart_seconds\tline\nhi\t1.0\t1\n")
    assert [c.word for c in CueTable.load(p).cues] == ["hi"]


# ------------------------------------------------------------------ queries

def test_lines_and_text():
    t = table(("never", 1.0, 1), ("mine", 1.4, 1), ("again", 2.0, 2))
    assert t.line_text(1) == "never mine"
    assert set(t.lines) == {1, 2}


def test_shift_moves_every_cue():
    t = table(("a", 1.0, 1), ("b", 2.0, 1))
    assert [c.start for c in t.shift(0.5).cues] == [1.5, 2.5]


def test_shift_preserves_spacing_even_past_zero():
    """Shift is a nudge, not a clamp.

    Pinning early cues at zero would silently compress the spacing between the
    first words while leaving the rest alone, which is a worse outcome than a
    negative time -- and `problems()` already reports negative starts, so the
    condition is visible rather than hidden.
    """
    t = table(("a", 0.2, 1), ("b", 1.2, 1))
    moved = t.shift(-5.0)
    gaps_before = [b.start - a.start for a, b in zip(t.cues, t.cues[1:])]
    gaps_after = [b.start - a.start for a, b in zip(moved.cues, moved.cues[1:])]
    assert gaps_after == pytest.approx(gaps_before)
    assert moved.problems(10.0) != [], "a negative start should be reported"


# --------------------------------------------------------------- validation

def test_a_clean_table_has_no_problems():
    assert table(("a", 1.0, 1), ("b", 2.0, 1), ("c", 3.0, 2)).problems(10.0) == []


def test_empty_table_is_reported():
    assert CueTable([]).problems() != []


def test_cue_past_the_end_of_the_track_is_reported():
    probs = table(("a", 1.0, 1), ("late", 99.0, 1)).problems(10.0)
    assert any("99" in p or "past" in p.lower() or "end" in p.lower() for p in probs)


def test_duplicate_timestamps_are_reported():
    assert table(("a", 1.0, 1), ("b", 1.0, 1)).problems(10.0) != []


def test_negative_start_is_reported():
    assert table(("a", -1.0, 1)).problems(10.0) != []


# --------------------------------------------------------------- from lines

def test_cues_from_lines_spreads_words():
    t = cues_from_lines(["one two", "three"], [0.0, 3.0])
    assert [c.word for c in t.cues] == ["one", "two", "three"]
    assert t.cues[0].start == 0.0
    assert t.cues[0].line != t.cues[-1].line
    assert all(a.start <= b.start for a, b in zip(t.cues, t.cues[1:]))
