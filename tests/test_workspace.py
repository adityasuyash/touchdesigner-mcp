"""One folder per song, and the guarantee that it really is one song per folder."""

from __future__ import annotations

from pathlib import Path

import pytest

from lyricfield.config import Config
from lyricfield.cues import Cue, CueTable
from lyricfield.workspace import Workspace, distinct_slug, slugify


# ------------------------------------------------------------------ slugging

def test_ascii_titles_slug_as_before():
    """Existing songs on disk must still resolve to their own folders."""
    assert slugify("August") == "august"
    assert slugify("August 2") == "august-2"
    assert slugify("Bunt x Sawariya") == "bunt-x-sawariya"


@pytest.mark.parametrize("title", ["बंट x सवारिया", "夏の歌", "Пісня", "أغنية"])
def test_non_latin_titles_keep_their_identity(title):
    """They used to all become the literal string "untitled", so the second
    such song moved into the first one's folder and inherited its lyrics."""
    slug = slugify(title)
    assert slug != "untitled"
    assert slug


def test_two_different_non_latin_titles_do_not_collide():
    assert slugify("बंट x सवारिया") != slugify("夏の歌")


def test_a_title_with_no_letters_at_all_still_gets_a_unique_name():
    a, b = slugify("!!!"), slugify("???")
    assert a and b and a != b


def test_slugs_are_safe_as_folder_names(tmp_path):
    for title in ("बंट x सवारिया", "夏の歌", "Song #1", "!!!"):
        d = tmp_path / slugify(title)
        d.mkdir()
        assert d.exists()


# ------------------------------------------------------- collision resolution

def test_a_free_slug_is_used_as_is(tmp_path):
    assert distinct_slug("August", tmp_path, lambda d: True) == "august"


def test_another_songs_folder_is_not_adopted(tmp_path):
    """The disaster case: two titles slug the same, and the second run opens
    the first song's folder, finds its cue table, and renders its words."""
    (tmp_path / "song-1").mkdir()
    got = distinct_slug("Song #1", tmp_path, belongs=lambda d: False)
    assert got != "song-1"
    assert got.startswith("song-1")


def test_the_same_song_keeps_its_own_folder(tmp_path):
    """Reuse is the wanted case -- it is what makes a run resumable."""
    (tmp_path / "august").mkdir()
    assert distinct_slug("August", tmp_path, belongs=lambda d: True) == "august"


# --------------------------------------------------------------- the folder

def test_create_lays_out_everything_a_song_needs(tmp_path):
    ws = Workspace.create("A Song", None, root=tmp_path)
    for d in (ws.dir, ws.source_dir, ws.stems_dir, ws.exports_dir, ws.stills_dir):
        assert d.is_dir()
    assert ws.config_path.exists()


def test_create_honours_an_explicit_slug(tmp_path):
    ws = Workspace.create("A Song", None, root=tmp_path, slug="a-song-2")
    assert ws.slug == "a-song-2"
    assert ws.dir.name == "a-song-2"


def test_open_of_a_missing_song_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        Workspace.open("nothing-here", root=tmp_path)


def test_export_path_never_overwrites_a_take(tmp_path):
    ws = Workspace.create("A Song", None, root=tmp_path)
    first = ws.export_path("preview")
    first.write_bytes(b"x")
    second = ws.export_path("preview")
    assert second != first
    assert not second.exists()


def test_a_take_records_what_produced_it(tmp_path):
    ws = Workspace.create("A Song", None, root=tmp_path)
    CueTable([Cue("hi", 1.0, 1)]).save(ws.cues_path)
    cfg = ws.load_config()
    cfg.params.look.dim_hue = 0.11
    ws.save_config(cfg)

    take = ws.export_path("preview")
    take.write_bytes(b"video")
    ws.write_take(take, ready=True)

    assert take.with_suffix(".toml").exists()
    assert take.with_suffix(".tsv").exists()
    assert take.with_suffix(".ready").exists()
    assert ws.takes()[0]["ready"] is True


def test_a_take_can_be_restored(tmp_path):
    ws = Workspace.create("A Song", None, root=tmp_path)
    CueTable([Cue("first", 1.0, 1)]).save(ws.cues_path)
    cfg = ws.load_config()
    cfg.params.look.dim_hue = 0.11
    ws.save_config(cfg)
    take = ws.export_path("preview")
    take.write_bytes(b"video")
    ws.write_take(take)

    moved = ws.load_config()
    moved.params.look.dim_hue = 0.99
    ws.save_config(moved)
    CueTable([Cue("second", 2.0, 1)]).save(ws.cues_path)

    ws.restore_take(take.stem)
    assert ws.load_config().params.look.dim_hue == 0.11
    assert [c.word for c in CueTable.load(ws.cues_path).cues] == ["first"]


def test_an_unready_take_has_no_marker(tmp_path):
    ws = Workspace.create("A Song", None, root=tmp_path)
    take = ws.export_path("preview")
    take.write_bytes(b"video")
    ws.write_take(take, ready=False)
    assert not take.with_suffix(".ready").exists()
    assert ws.takes()[0]["ready"] is False
