"""What the gallery picked is what gets rendered.

The picked renderer used to be dropped twice over on its way to the render: the
UI never sent it, and the run stage that owns the config only honoured it while
*creating* a song. Both failures looked like success -- the run reported the
stage done and rendered the old renderer -- so both are pinned here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from lyricfield import run as run_mod
from lyricfield import types as types_mod
from lyricfield.workspace import Workspace

REPO = Path(__file__).resolve().parents[1]
INDEX = REPO / "lyricfield" / "ui" / "static" / "index.html"

BEATSYNC = [vt.slug for vt in types_mod.list_types()
            if vt.family == types_mod.BEATSYNC]


@pytest.fixture
def song(tmp_path):
    """A song already on disk, made as the default renderer."""
    return Workspace.create("Pick Test", root=tmp_path, copy_source=False)


def _ctx(ws, **kw):
    ctx = run_mod.Ctx(client=None, name=ws.name, **kw)
    ctx.workspace = ws
    return ctx


# ------------------------------------------------------------------ the run

@pytest.mark.skipif(not BEATSYNC, reason="no beatsync type registered")
def test_an_existing_song_switches_to_the_picked_renderer(song):
    assert song.load_config().type == types_mod.DEFAULT_TYPE
    said = []
    changed = run_mod._honour_pick(_ctx(song, video_type=BEATSYNC[0]), said.append)
    assert changed["type"] == BEATSYNC[0]
    assert song.load_config().type == BEATSYNC[0]
    assert any("switched" in m for m in said)


def test_picking_the_renderer_it_already_has_changes_nothing(song):
    """Re-running a tuned song must not reset its tunables to the defaults."""
    cfg = song.load_config()
    section = next(iter(cfg.params.__dataclass_fields__))
    name, value = next(iter(vars(getattr(cfg, section)).items()))
    bumped = (value + 1) if isinstance(value, (int, float)) else value
    setattr(getattr(cfg, section), name, bumped)
    song.save_config(cfg)

    run_mod._honour_pick(_ctx(song, video_type=types_mod.DEFAULT_TYPE), lambda m: None)
    assert getattr(getattr(song.load_config(), section), name) == bumped


def test_an_unknown_renderer_is_reported_rather_than_applied(song):
    said = []
    run_mod._honour_pick(_ctx(song, video_type="no_such_type"), said.append)
    assert song.load_config().type == types_mod.DEFAULT_TYPE
    assert any("no video type" in m for m in said)


def test_no_pick_at_all_leaves_the_song_alone(song):
    assert run_mod._honour_pick(_ctx(song), lambda m: None) == {}
    assert song.load_config().type == types_mod.DEFAULT_TYPE


# --------------------------------------------------------- the backdrop

BACKDROPS = [b[0] for b in
             types_mod.get_type(types_mod.DEFAULT_TYPE)._params_module().BACKDROPS]


@pytest.mark.parametrize("key", BACKDROPS)
def test_every_offered_backdrop_can_actually_be_applied(key, tmp_path):
    """The UI offers exactly these, so every one of them has to work.

    `none` did not. Its own preset -- no decoration, no backdrop -- tripped a
    `validate()` rule against leaving the lyric gaps black, so the one choice
    that expresses "the words alone" was the one choice that could not be made.
    That rule is a note now: `validate()` means the render cannot be trusted,
    not that the look is unusual.
    """
    ws = Workspace.create(f"Backdrop {key}", root=tmp_path, copy_source=False)
    said = []
    changed = run_mod._honour_pick(_ctx(ws, backdrop=key), said.append)
    assert changed.get("backdrop") == key, said
    assert ws.load_config().validate() == []


def test_the_backdrop_and_the_word_look_compose(tmp_path):
    """The whole point: one video wearing both."""
    ws = Workspace.create("Both", root=tmp_path, copy_source=False)
    run_mod._honour_pick(
        _ctx(ws, video_type=types_mod.DEFAULT_TYPE, backdrop="pulse"),
        lambda m: None)
    cfg = ws.load_config()
    assert cfg.type == types_mod.DEFAULT_TYPE      # still the lyric renderer
    assert cfg.video_type.needs_lyrics             # still draws the words
    assert cfg.backdrop.back_level > 0             # and a field behind them
    assert cfg.backdrop.back_wave > 0


def test_an_unknown_backdrop_is_reported_rather_than_applied(tmp_path):
    ws = Workspace.create("Unknown backdrop", root=tmp_path, copy_source=False)
    before = ws.load_config().backdrop.back_level
    said = []
    changed = run_mod._honour_pick(_ctx(ws, backdrop="nonsense"), said.append)
    assert "backdrop" not in changed
    assert ws.load_config().backdrop.back_level == before
    assert any("no 'nonsense' backdrop" in m for m in said)


def test_words_alone_says_what_it_implies(tmp_path):
    ws = Workspace.create("Words alone", root=tmp_path, copy_source=False)
    said = []
    run_mod._honour_pick(_ctx(ws, backdrop="none"), said.append)
    assert any("black" in m for m in said), said


# ------------------------------------------------------------------- the UI

def test_the_ui_sends_the_selected_type_with_the_run():
    body = re.search(r"function runBody\(extra\) \{(.+?)\n\}", INDEX.read_text(), re.S)
    assert body, "runBody() is gone or was renamed"
    assert "type:" in body.group(1), "runBody() does not send the renderer"
    assert "backdrop:" in body.group(1), "runBody() does not send the backdrop"


def test_the_gallery_offers_a_row_for_what_sits_behind_the_words():
    src = INDEX.read_text()
    assert "backdropRow" in src and "Behind the words" in src, \
        "the gallery has no picker for the backdrop"


def test_a_pick_is_not_overwritten_by_a_config_refresh():
    """`refreshAll` runs on song select and when a run finishes. It used to
    adopt the server's type unconditionally, so choosing a song after picking a
    tile silently put the tile back."""
    src = INDEX.read_text()
    ref = re.search(r"async function refreshAll\(\) \{(.+?)\n\}", src, re.S)
    assert ref, "refreshAll() is gone or was renamed"
    assert "PICKED" in ref.group(1), \
        "refreshAll() overwrites the gallery selection unconditionally"


def test_the_gallery_offers_every_registered_renderer():
    """It used to group the *styles* on disk, so a renderer with no style yet
    -- every beatsync one -- had no tile and could not be picked."""
    src = INDEX.read_text()
    gal = re.search(r"function renderGallery\(\) \{(.+?)\n\}", src, re.S)
    assert gal and "TYPES" in gal.group(1), \
        "the gallery does not build its tiles from the registered types"


def test_the_custom_preview_is_not_pinned_to_one_renderer():
    src = INDEX.read_text()
    assert "/styles/lyric_grid/${CUSTOM_SLUG}" not in src, \
        "the custom-look preview path hardcodes lyric_grid"
