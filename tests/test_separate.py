"""Stem separation: which stems, and when it is allowed to skip.

Nothing tested this file at all, which matters most for the skip: it is the one
decision that can leave a caller holding a path to a file that does not exist,
and nothing downstream asserts a stem is on disk.
"""

from __future__ import annotations

import pytest

from lyricfield import separate as SEP
from lyricfield import types as types_mod


def _lay(folder, names):
    folder.mkdir(parents=True, exist_ok=True)
    for n in names:
        (folder / f"{n}.wav").write_bytes(b"RIFF....WAVE")


# ---------------------------------------------------------- what it asks for

def test_it_asks_for_every_stem_now(tmp_path):
    """`--two-stems` computed drums, bass and other, summed them and threw them
    away. The model runs identically either way, so the stem this project most
    needs was being produced and deleted on every separation it has ever run."""
    st = SEP.stem_paths(tmp_path / "song.mp3", root=tmp_path)
    assert st.drums and st.drums.name == "drums.wav"
    assert st.bass and st.other
    assert st.vocals.name == "vocals.wav"
    assert st.instrumental.name == "no_vocals.wav"


def test_the_old_two_stem_layout_can_still_be_described(tmp_path):
    st = SEP.stem_paths(tmp_path / "song.mp3", root=tmp_path, all_stems=False)
    assert st.drums is None and st.bass is None and st.other is None
    assert st.rhythm is None


# ------------------------------------------------------------ existence

def test_a_four_stem_set_is_incomplete_without_the_drums(tmp_path):
    """If `exists` only checked the two it used to, every song separated before
    this change would report itself complete and hand out a drums path pointing
    at nothing."""
    st = SEP.stem_paths(tmp_path / "song.mp3", root=tmp_path)
    _lay(st.vocals.parent, ["vocals", "no_vocals"])
    assert not st.exists
    _lay(st.vocals.parent, ["drums", "bass", "other"])
    assert st.exists


def test_a_two_stem_set_is_complete_with_two(tmp_path):
    st = SEP.stem_paths(tmp_path / "song.mp3", root=tmp_path, all_stems=False)
    _lay(st.vocals.parent, ["vocals", "no_vocals"])
    assert st.exists


def test_rhythm_is_the_drums_stem_only_when_there_is_one(tmp_path):
    st = SEP.stem_paths(tmp_path / "song.mp3", root=tmp_path)
    assert st.rhythm is None                      # nothing on disk yet
    _lay(st.vocals.parent, ["drums"])
    assert st.rhythm == st.drums


# ----------------------------------------------------------- the skip

def test_an_existing_two_stem_song_is_not_re_separated(tmp_path, monkeypatch):
    """Re-running demucs is minutes of work the user did not ask for. An old
    song keeps what it has and is described honestly; "Separate again" is how
    it gets upgraded."""
    monkeypatch.setattr(SEP, "find_demucs",
                        lambda: pytest.fail("demucs was run"))
    track = tmp_path / "song.mp3"
    track.write_bytes(b"x")
    old = SEP.stem_paths(track, root=tmp_path, all_stems=False)
    _lay(old.vocals.parent, ["vocals", "no_vocals"])

    said = []
    got = SEP.separate(track, root=tmp_path, progress=said.append)
    assert got.drums is None, "reported a drums stem that is not there"
    assert got.rhythm is None
    assert any("two-stem" in m for m in said), said


def test_a_fully_separated_song_is_not_re_separated(tmp_path, monkeypatch):
    monkeypatch.setattr(SEP, "find_demucs",
                        lambda: pytest.fail("demucs was run"))
    track = tmp_path / "song.mp3"
    track.write_bytes(b"x")
    st = SEP.stem_paths(track, root=tmp_path)
    _lay(st.vocals.parent, ["vocals", "no_vocals", "drums", "bass", "other"])
    got = SEP.separate(track, root=tmp_path, progress=lambda m: None)
    assert got.rhythm == got.drums


# ------------------------------------------------------ nothing skips it

def test_no_video_type_can_analyse_a_raw_mix():
    """Every renderer answers the beat, so every one needs the drums isolated.
    A type asking only for the mix is a type whose beat response fires on the
    bassline."""
    for vt in types_mod.list_types():
        assert vt.needs_separation, f"{vt.slug} would skip separation"
        assert types_mod.DRUMS in vt.needs, f"{vt.slug} does not ask for drums"
