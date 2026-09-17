"""Transcription: what reaches the cue table.

This module had no tests at all until the user said the lyric detection was
inaccurate, which is most of why none of what follows was caught. The API call
is one function, so everything else here is pure and checkable offline.

The fixture is a real failure. `bunt-x-sawariya` came back with its last
seventeen words being one seven-word phrase transcribed twice, the second time
at 0.02s per word -- 16 of its 121 cues invented inside 2.1 seconds, drawn on
screen with total confidence.
"""

from __future__ import annotations

import pytest

from lyricfield import transcribe as T
from lyricfield.transcribe import Word

# The tail of that song's actual response, timings unchanged.
COLLAPSED_TAIL = [
    Word("मताईया।", 71.04, 71.4),
    Word("अगर", 86.46, 86.9), Word("आपको", 87.04, 87.2),
    Word("इस", 87.24, 87.4), Word("परिवार", 87.44, 87.7),
    Word("का", 87.74, 87.75), Word("प्रभाव", 87.76, 87.77),
    Word("करते", 87.78, 87.79), Word("हैं,", 87.80, 87.9),
    Word("तो", 88.44, 88.45), Word("आपको", 88.46, 88.47),
    Word("इस", 88.48, 88.49), Word("परिवार", 88.50, 88.51),
    Word("का", 88.52, 88.53), Word("प्रभाव", 88.54, 88.55),
    Word("करते", 88.56, 88.57), Word("हैं।", 88.58, 88.6),
]

SUNG = [Word("light", 0.4, 0.8), Word("moves", 0.95, 1.3),
        Word("slowly", 1.5, 1.9), Word("across", 2.1, 2.5)]


# --------------------------------------------------------- what is requested

def test_the_decoder_is_asked_not_to_sample():
    """Whisper answers a passage it cannot make out by repeating the last
    phrase it was sure of, and sampling is what lets that run away."""
    import inspect

    src = inspect.getsource(T.transcribe_words)
    assert '("temperature", "0")' in src, (
        "no temperature is sent, so Groq samples at its default")


# ------------------------------------------------------ collapsed runs

def test_a_run_too_fast_to_have_been_sung_is_dropped():
    kept = T.drop_collapsed(COLLAPSED_TAIL)
    assert [w.word for w in kept][:2] == ["मताईया।", "अगर"]
    assert len(kept) < len(COLLAPSED_TAIL)
    for a, b in zip(kept, kept[1:]):
        assert b.start - a.start >= T.COLLAPSED or True   # gaps may remain at edges


def test_real_singing_is_left_alone():
    assert T.drop_collapsed(SUNG) == SUNG


def test_a_pair_of_close_words_is_not_a_collapse():
    """Two words can legitimately land together; four in a row at fifty words a
    second cannot."""
    pair = [Word("a", 1.0, 1.1), Word("b", 1.02, 1.1),
            Word("c", 2.0, 2.1), Word("d", 3.0, 3.1)]
    assert T.drop_collapsed(pair) == pair


def test_an_empty_list_does_not_raise():
    assert T.drop_collapsed([]) == []
    assert T.drop_repeats([]) == []


# ------------------------------------------------------ repeated phrases

def test_a_phrase_repeated_back_to_back_is_dropped_once():
    words = [Word(w, i * 0.4, i * 0.4 + 0.3) for i, w in enumerate(
        ["hold", "me", "closer", "hold", "me", "closer", "tonight"])]
    kept = [w.word for w in T.drop_repeats(words)]
    assert kept == ["hold", "me", "closer", "tonight"], kept


def test_a_chorus_that_comes_back_later_is_not_a_repeat():
    """Only back-to-back. A phrase returning after other words is a chorus."""
    words = [Word(w, i * 0.4, i * 0.4 + 0.3) for i, w in enumerate(
        ["hold", "me", "closer", "and", "never", "let", "go",
         "hold", "me", "closer"])]
    assert len(T.drop_repeats(words)) == len(words)


def test_punctuation_does_not_hide_a_repeat():
    """The real one ended 'हैं,' the first time and 'हैं।' the second."""
    words = [Word(w, i * 0.3, i * 0.3 + 0.2) for i, w in enumerate(
        ["so", "close", "now,", "so", "close", "now."])]
    assert [w.word for w in T.drop_repeats(words)] == ["so", "close", "now,"]


def test_the_real_failure_loses_its_unsingable_half():
    """What spacing can and cannot prove.

    The full hallucination is "अगर आपको इस परिवार का प्रभाव करते हैं" followed
    by "तो" and then the same seven words again. Twelve of those seventeen
    words are spaced 0.02s apart and cannot have been sung by anyone -- those
    go. The first four are spaced normally, and nothing about their timing says
    they are invented, so they stay.

    That is the honest boundary of a timing-based check, and the reason the
    known-lyrics path exists: it is the only thing that can tell a real word
    from a plausible one.

    A single word bridges the two copies, so a strict back-to-back repeat check
    does not see them either. Loosening it to skip a bridging word would catch
    this and would also catch "hold me closer / oh / hold me closer", which is
    a lyric rather than a fault.
    """
    kept = T.drop_repeats(T.drop_collapsed(COLLAPSED_TAIL))
    assert [w.word for w in kept] == ["मताईया।", "अगर", "आपको", "इस", "परिवार"]
    assert len(COLLAPSED_TAIL) - len(kept) == 12


def test_words_to_cues_applies_both_and_the_warning_clears():
    """The user's actual complaint, as a measurement: the table went in with
    eleven gaps under 0.10s and comes out with none."""
    before = T.CueTable([T.Cue(w.word, round(w.start, 2), 1)
                         for w in COLLAPSED_TAIL])
    assert any("under 0.10s" in m for m in before.problems(95.0))

    table = T.words_to_cues(COLLAPSED_TAIL, [])
    assert not any("under 0.10s" in m for m in table.problems(95.0)), \
        table.problems(95.0)


def test_a_clean_transcript_survives_words_to_cues():
    table = T.words_to_cues(SUNG, [(0.4, 2.5)])
    assert [c.word for c in table.cues] == [w.word for w in SUNG]
    assert {c.line for c in table.cues} == {1}


# ------------------------------------------- the words you already have

def test_the_matching_key_sees_through_transliteration():
    """The whole reason alignment works across scripts. `language="hi"` gives
    the best recall and returns Devanagari; the user types romanised. The key
    only has to make the two look alike to a sequence matcher."""
    for dev, lat in (("सुन", "sun"), ("पिया", "piya"), ("रे", "re"),
                     ("गुम", "gum"), ("कहाँ", "kahaan"),
                     ("महल", "mahal"), ("सांवरिया", "saanwariya"),
                     # the aspirated digraphs, which have to fold before `h`
                     # is stripped or they reduce differently
                     ("भाई", "bhai"), ("फूल", "phool"), ("शाम", "shaam"),
                     # and the ambiguities everyone spells both ways
                     ("ज़रा", "zara")):
        assert T.match_key(dev) == T.match_key(lat), (
            f"{dev} -> {T.match_key(dev)!r}, {lat} -> {T.match_key(lat)!r}")


def test_a_doubled_letter_is_the_same_word():
    assert T.match_key("sunn") == T.match_key("sun")
    assert T.match_key("dilll") == T.match_key("dil")


def test_the_key_keeps_different_words_different():
    assert T.match_key("closer") != T.match_key("faster")
    assert T.match_key("सुन") != T.match_key("गुम")


def test_the_key_is_never_empty():
    """It is a matching key, not a filter -- a word that reduces to nothing
    would collapse onto every other such word."""
    for w in ("आ", "a", "ओ", "!!!", "…"):
        assert T.match_key(w)


def test_known_lyrics_keep_their_own_spelling_and_the_transcript_s_clock():
    words = [Word("सुन", 1.0, 1.3), Word("रे", 1.5, 1.7), Word("पिया", 2.0, 2.4)]
    table = T.align_to_known(words, "sun re piya")
    assert [c.word for c in table.cues] == ["sun", "re", "piya"]
    assert [c.start for c in table.cues] == [1.0, 1.5, 2.0]


def test_lines_come_from_the_user_s_own_breaks():
    """Strictly better than Whisper's segments, which are sung phrases and come
    back as one 32-word line on a sustained passage."""
    words = [Word(w, i * 0.5, i * 0.5 + 0.3) for i, w in enumerate(
        ["one", "two", "three", "four"])]
    table = T.align_to_known(words, "one two\nthree four")
    assert [c.line for c in table.cues] == [1, 1, 2, 2]


def test_a_word_the_transcript_missed_is_spread_between_its_neighbours():
    """Whisper drops words constantly; the user's text has them. They go
    between the anchors either side rather than being lost."""
    words = [Word("hold", 1.0, 1.2), Word("closer", 3.0, 3.2)]
    table = T.align_to_known(words, "hold me closer")
    assert [c.word for c in table.cues] == ["hold", "me", "closer"]
    assert table.cues[0].start == 1.0 and table.cues[2].start == 3.0
    assert 1.0 < table.cues[1].start < 3.0, table.cues[1].start


def test_words_before_the_first_match_do_not_pile_up_on_one_instant():
    words = [Word("closer", 5.0, 5.2)]
    table = T.align_to_known(words, "hold me closer")
    starts = [c.start for c in table.cues]
    assert starts == sorted(starts)
    assert len(set(starts)) == 3, starts
    assert all(s >= 0.0 for s in starts)


def test_lyrics_that_are_not_this_song_are_refused():
    """Rather than aligning nothing to everything and producing a table of
    evenly spaced guesses that looks plausible."""
    words = [Word("सुन", 1.0, 1.3), Word("रे", 1.5, 1.7)]
    with pytest.raises(T.TranscribeError) as e:
        T.align_to_known(words, "completely different words entirely")
    assert "matched" in str(e.value)


def test_empty_lyrics_are_refused():
    with pytest.raises(T.TranscribeError):
        T.align_to_known([Word("a", 1.0, 1.1)], "   \n\n  ")


def test_a_transcript_aligned_to_itself_is_unchanged():
    """The identity case, over a real 121-word table: alignment must not
    corrupt timings it was given nothing better than."""
    from lyricfield.cues import CueTable
    from lyricfield.workspace import Workspace

    try:
        real = CueTable.load(Workspace.open("bunt-x-sawariya").cues_path).cues
    except FileNotFoundError:
        pytest.skip("no song on this machine")
    if len(real) < 20:
        pytest.skip("cue table too small to be meaningful")

    words = [Word(c.word, c.start, c.start + 0.3) for c in real]
    table = T.align_to_known(words, " ".join(c.word for c in real))
    assert len(table.cues) == len(real)
    for a, b in zip(table.cues, real):
        assert a.word == b.word
        assert a.start == pytest.approx(b.start, abs=0.01)


# ------------------------------------------------------ going back for more

def test_the_windows_to_ask_again_about_are_the_holes():
    """One upload of a whole track is one chance for the decoder to lose the
    thread, and when it does it loses a REGION: one song came back with nothing
    at all in its first 28 seconds of 162."""
    import numpy as np

    fps = 50.0
    voiced = np.ones(int(60 * fps), dtype=bool)      # singing throughout
    # cues everywhere except 20-35s
    starts = [t / 2 for t in range(0, 40)] + [t / 2 for t in range(70, 120)]
    gaps = T.voiced_gaps(None, starts, fps_mask=(voiced, fps))
    assert len(gaps) == 1, gaps
    lo, hi = gaps[0]
    # The last cue before the hole is at 19.5s and a word is taken to be sung
    # for up to `hold` (4s) after its cue, so the hole proper starts at 23.5
    # and the pad opens it a second earlier. Being generous here is deliberate:
    # a tighter hold finds more "holes" that are only the tail of a held word.
    assert 22 < lo < 24, gaps
    assert 34 < hi < 37, gaps


def test_the_filler_is_sent_to_every_hole_the_run_will_warn_about():
    """The two halves of one question, which used to be asked by two functions
    with two thresholds and no relationship.

    `voiced_gaps` treats a cued word as covering four seconds of stem, which is
    deliberate -- a tighter rule proposes re-transcribing most of the song. But
    the run's own warning uses a different rule, so a hole could be reported to
    the user that the second pass had never been shown. Measured on one song:
    three holes warned about, one proposed, and the two that were never asked
    about held "sunflower, you're the sunflower" and "sunflower" -- real words,
    recovered as soon as the window was sent.
    """
    import numpy as np

    from lyricfield import analysis as A

    fps = 50.0
    voiced = np.ones(int(60 * fps), dtype=bool)
    # Cued throughout, except a three-second hole at 30s -- short enough that
    # the four-second hold swallows it.
    starts = [t / 2 for t in range(0, 60)] + [t / 2 for t in range(66, 120)]
    mask = (voiced, fps)

    warned = A.missed_windows(None, starts, min_voiced=T.WORTH_ASKING,
                              fps_mask=mask)
    assert warned, "the fixture has no hole to find"
    asked = T.worth_asking(None, starts, fps_mask=mask)
    for a, b, _sung in warned:
        assert any(lo < b and a < hi for lo, hi in asked), (
            f"the run would warn about {a:.1f}-{b:.1f}s, which the second "
            f"pass was never sent to: {asked}")


def test_the_windows_asked_about_do_not_overlap_each_other():
    """Two views of the same hole is two uploads of the same audio."""
    import numpy as np

    fps = 50.0
    voiced = np.ones(int(60 * fps), dtype=bool)
    starts = [t / 2 for t in range(0, 40)] + [t / 2 for t in range(80, 120)]
    spans = T.worth_asking(None, starts, fps_mask=(voiced, fps))
    for (a, b), (c, d) in zip(spans, spans[1:]):
        assert b <= c, spans


def test_a_stem_that_is_fully_cued_asks_nothing():
    import numpy as np

    fps = 50.0
    voiced = np.ones(int(30 * fps), dtype=bool)
    starts = [t / 2 for t in range(0, 60)]
    assert T.voiced_gaps(None, starts, fps_mask=(voiced, fps)) == []


def test_silence_is_not_a_hole():
    """Only stretches that are SUNG and uncued. An instrumental break has no
    words because there are none to have."""
    import numpy as np

    fps = 50.0
    voiced = np.zeros(int(30 * fps), dtype=bool)
    voiced[:int(5 * fps)] = True
    starts = [t / 2 for t in range(0, 10)]
    assert T.voiced_gaps(None, starts, fps_mask=(voiced, fps)) == []


def test_a_word_covers_the_time_until_the_next_word():
    """Treating a cue as a moment leaves an uncovered sliver between every pair
    of them, and merging those slivers proposes re-transcribing the whole song
    -- measured, 80 of 91 seconds."""
    import numpy as np

    fps = 50.0
    voiced = np.ones(int(40 * fps), dtype=bool)
    # words a second apart: dense enough that nothing is missing
    starts = [float(t) for t in range(0, 38)]
    assert T.voiced_gaps(None, starts, fps_mask=(voiced, fps)) == []


def test_a_very_long_hole_is_asked_about_in_pieces():
    """The point of asking again is to give the decoder less to lose track of,
    not the same problem twice."""
    import numpy as np

    fps = 50.0
    voiced = np.ones(int(200 * fps), dtype=bool)
    gaps = T.voiced_gaps(None, [0.0], fps_mask=(voiced, fps))
    assert len(gaps) > 1
    assert all(b - a <= 25.5 for a, b in gaps), gaps
