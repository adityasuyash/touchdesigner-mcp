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
from lyricfield import styles as S
from lyricfield import types as types_mod
from lyricfield.workspace import Workspace

REPO = Path(__file__).resolve().parents[1]
INDEX = REPO / "lyricfield" / "ui" / "static" / "index.html"

OTHER = [vt.slug for vt in types_mod.list_types()
         if vt.slug != types_mod.DEFAULT_TYPE]


@pytest.fixture
def song(tmp_path):
    """A song already on disk, made as the default renderer."""
    return Workspace.create("Pick Test", root=tmp_path, copy_source=False)


def _ctx(ws, **kw):
    ctx = run_mod.Ctx(client=None, name=ws.name, **kw)
    ctx.workspace = ws
    return ctx


# ------------------------------------------------------------------ the run

def test_an_existing_song_switches_to_the_picked_renderer(song):
    assert song.load_config().type == types_mod.DEFAULT_TYPE
    said = []
    changed = run_mod._honour_pick(_ctx(song, video_type=OTHER[0]), said.append)
    assert changed["type"] == OTHER[0]
    assert song.load_config().type == OTHER[0]
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


def test_picking_a_style_applies_it(song):
    """The case that crashed, and that nothing covered.

    `_honour_pick` was exercised with `video_type=` and `back_style=` and never
    with `style=` -- so a line reading `ctx.type`, which `Ctx` does not have,
    shipped and killed every run where a look was chosen.
    """
    from lyricfield import styles as S

    st = next(iter(S.list_styles()), None)
    if st is None:
        pytest.skip("no styles ship on this machine")
    said = []
    changed = run_mod._honour_pick(
        _ctx(song, video_type=st.type, style=st.slug), said.append)
    assert changed.get("style") == st.slug, said
    assert song.load_config().track.style == st.slug


def test_picking_a_style_by_name_alone_still_works(song):
    """A bare slug, with no renderer beside it. The resolution has to fall back
    to "whichever renderer owns it" rather than reaching for an attribute that
    is not there."""
    from lyricfield import styles as S

    owned = {}
    for s in S.list_styles():
        owned.setdefault(s.slug, []).append(s)
    unique = next((v[0] for v in owned.values() if len(v) == 1), None)
    if unique is None:
        pytest.skip("every shipped slug is shared between renderers")
    changed = run_mod._honour_pick(
        _ctx(song, style=unique.slug), lambda m: None)
    assert changed.get("style") == unique.slug


def test_no_pick_at_all_leaves_the_song_alone(song):
    assert run_mod._honour_pick(_ctx(song), lambda m: None) == {}
    assert song.load_config().type == types_mod.DEFAULT_TYPE


# The "layer behind" section lived here: a beat renderer composited under
# the words. It is gone with the beatsync family -- the beat is an effect on
# the word layer now, and `tests/test_beat.py` owns that.


# ------------------------------------------------------------------- the UI

def test_the_ui_sends_the_selected_type_with_the_run():
    body = re.search(r"function runBody\(extra\) \{(.+?)\n\}", INDEX.read_text(), re.S)
    assert body, "runBody() is gone or was renamed"
    assert "type:" in body.group(1), "runBody() does not send the renderer"
    assert "back_style:" in body.group(1), "runBody() does not send the beat pick"


def test_the_two_rows_hold_independent_picks():
    """One TYPE_SLUG for both rows is what made them mutually exclusive: a
    beatsync click un-lit the lyric tile."""
    src = INDEX.read_text()
    assert "BACK_TYPE" in src and "BACK_STYLE" in src
    assert "function setPick(fam, type, style)" in src, \
        "clicks do not write per-row picks"
    assert "function noneCard(fam)" in src, \
        "no None tile, so neither row can be left empty"


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


# ------------------------------------------------------- where it starts

def test_a_deliberate_zero_start_survives_the_trip():
    """`{...}.items() if v` used truthiness to mean "was this provided", so
    `start_seconds = 0` was dropped before it reached the run — which then fell
    through to the auto-pick and began at the busiest stretch of CUES, i.e. the
    singing. `run.py` already guarded the far end; the value never got there.
    """
    from lyricfield import run as rm
    from lyricfield.ui import server

    seen = {}

    def fake_start(run, ctx, on_change=None, from_stage=None):
        seen["opts"] = dict(ctx.options)

    orig, server.RUN = rm.start, None
    rm.start = fake_start
    try:
        server.start_run(server.RunIn(name="x", start_seconds=0.0))
        assert seen["opts"].get("start_seconds") == 0.0
        server.RUN = None
        server.start_run(server.RunIn(name="x", start_seconds=12.5))
        assert seen["opts"].get("start_seconds") == 12.5
        server.RUN = None
        server.start_run(server.RunIn(name="x"))
        assert "start_seconds" not in seen["opts"], "absent must stay absent"
    finally:
        rm.start = orig
        server.RUN = None


def test_zero_is_honoured_as_a_start_not_treated_as_absent():
    """The consumer's half of the same bug, asserted so it cannot regress."""
    import inspect

    from lyricfield import run as rm
    src = inspect.getsource(rm._preview)
    assert 'chosen not in (None, "")' in src, \
        "the start check is back to truthiness, which cannot see a deliberate 0"


def test_the_ui_offers_the_three_start_choices():
    src = INDEX.read_text()
    for mark in ('data-start="begin"', 'data-start="vocals"', 'data-start="at"'):
        assert mark in src, f"no {mark} button"
    assert "function startSeconds()" in src
    assert "vocal_in" in src, "the vocals option has no measured entry to use"


# -------------------------------------------------------------- the footage

def test_footage_can_be_set_on_a_song_that_already_exists(song, tmp_path):
    """The defect class this whole function exists for: a choice accepted,
    acknowledged and then discarded. `Workspace.create` honours the plate, so a
    NEW song was always right; an existing one would have ignored it."""
    clip = tmp_path / "coast.mp4"
    clip.write_bytes(b"not really a movie")
    changed = run_mod._honour_pick(_ctx(song, plate=str(clip)), lambda m: None)
    assert changed.get("plate")
    assert song.load_config().track.plate.endswith("coast.mp4")


def test_footage_is_copied_into_the_song_folder(song, tmp_path):
    """A song folder that depends on a file elsewhere stops rendering the day
    that file moves -- which is why the audio is copied in too."""
    clip = tmp_path / "coast.mp4"
    clip.write_bytes(b"not really a movie")
    run_mod._honour_pick(_ctx(song, plate=str(clip)), lambda m: None)
    got = Path(song.load_config().track.plate)
    assert got.parent == song.source_dir, got
    assert got.exists()


def test_no_footage_leaves_the_song_alone(song):
    assert "plate" not in run_mod._honour_pick(_ctx(song), lambda m: None)
    assert song.load_config().track.plate == ""


def test_the_ui_sends_the_footage_with_the_run():
    body = re.search(r"function runBody\(extra\) \{(.+?)\n\}", INDEX.read_text(), re.S)
    assert body and "plate:" in body.group(1), "runBody() does not send the footage"


def test_the_picker_asks_for_the_kind_of_file_it_is_filling():
    """One modal serves both fields, and the server owns the extension sets --
    the client only says which kind it wants."""
    src = INDEX.read_text()
    assert "BROWSE_FOR" in src and "kind: 'plate'" in src
    assert "kind: want.kind" in src or "kind: want.kind" in src or "want.kind" in src


def test_the_language_and_lyrics_are_remembered_on_the_song(song):
    """So a re-run with the fields untouched does not revert to auto-detect."""
    run_mod._honour_pick(
        _ctx(song, options={"language": "hi", "prompt": "sun re piya"}),
        lambda m: None)
    cfg = song.load_config()
    assert cfg.track.language == "hi"
    assert cfg.track.lyrics == "sun re piya"


def test_what_the_run_carries_beats_what_the_song_remembers(song):
    run_mod._honour_pick(_ctx(song, options={"language": "hi"}), lambda m: None)
    run_mod._honour_pick(_ctx(song, options={"language": "ur"}), lambda m: None)
    assert song.load_config().track.language == "ur"


def test_an_empty_field_does_not_wipe_what_was_stored(song):
    """Leaving the box blank on a re-run means "as before", not "forget"."""
    run_mod._honour_pick(_ctx(song, options={"language": "hi"}), lambda m: None)
    run_mod._honour_pick(_ctx(song, options={"language": ""}), lambda m: None)
    assert song.load_config().track.language == "hi"


# ------------------------------------------- every choice, in one place

def test_the_creation_flow_carries_every_subjective_choice():
    """A setting the user has an opinion about belongs where they are already
    looking, not behind a pane they have to know to visit. Language lived in
    the Words pane and the known lyrics in Song setup, so neither was available
    when the first video was made."""
    src = INDEX.read_text()
    make = src[src.index('id="view-make"'):src.index('id="view-preview"')]
    for want in ('id="lang"', 'id="prompt"', 'data-look-host',
                 'id="runName"', 'id="runSource"', 'id="runPlate"'):
        assert want in make, f"{want} is not in the creation flow"


def test_the_extra_choices_open_closed():
    """Progressive disclosure: the pane still has to read as name, look, beat,
    go. A wall of inputs is the thing this is not."""
    src = INDEX.read_text()
    for panel in ('id="moreWords"', 'id="moreLook"'):
        i = src.index(panel)
        tag = src[src.rindex('<details', 0, i):i]
        assert 'open' not in tag, f"{panel} starts expanded"


def test_one_renderer_draws_the_look_controls_in_both_places():
    """Two hosts, one implementation, so the Look pane and the creation flow
    cannot drift."""
    src = INDEX.read_text()
    assert "function drawControls(host)" in src
    assert "querySelectorAll('[data-look-host]')" in src


def test_a_new_song_starts_from_a_blank_form():
    """It used to switch pane and leave the last song's name and paths sitting
    there, ready to be submitted against a different song. `refreshAll` only
    prefills a field that is EMPTY, so nothing was going to overwrite them."""
    src = INDEX.read_text()
    assert "function clearForm()" in src
    body = re.search(r"function clearForm\(\) \{(.+?)\n\}", src, re.S).group(1)
    for id_ in ("runName", "runSource", "runPlate", "lang", "prompt"):
        assert id_ in body, f"clearForm leaves #{id_} alone"
    assert "PICKED = false" in body, "the gallery pick survives a new song"
    assert "if (!slug) clearForm();" in src, "clearForm is never called"
