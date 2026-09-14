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
from lyricfield.types.lyric_grid import params as P
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

BEATSYNC_STYLES = [st for st in S.list_styles()
                   if types_mod.get_type(st.type).family == types_mod.BEATSYNC]

# Only the beat looks that draw into the grid's own character field can become
# the layer BEHIND lyric_grid's words. `rings`, `strata` and `scope` have their
# own networks; there is no sense in which one renderer's picture is another
# renderer's ambient layer. This was free to assume while every beatsync type
# WAS the grid.
BACKABLE = [st for st in BEATSYNC_STYLES if P.can_back_words(st.params)]


@pytest.mark.parametrize("st", BACKABLE, ids=[s.slug for s in BACKABLE])
def test_a_grid_beat_style_can_go_behind_the_words(st, tmp_path):
    """The thing that was asked for: a lyric look AND a beat look, together."""
    ws = Workspace.create(f"Behind {st.slug}", root=tmp_path, copy_source=False)
    said = []
    changed = run_mod._honour_pick(
        _ctx(ws, video_type=types_mod.DEFAULT_TYPE,
             back_type=st.type, back_style=st.slug), said.append)
    assert "backdrop" in changed, said
    cfg = ws.load_config()
    assert cfg.type == types_mod.DEFAULT_TYPE      # still the lyric renderer
    assert cfg.video_type.needs_lyrics             # still draws the words
    assert cfg.backdrop.back_level > 0             # and a field behind them
    assert cfg.track.back_style == st.slug
    assert cfg.validate() == []


def test_the_five_looks_stay_distinguishable_behind_words():
    """They collapsed into about three under the first translation: the kick was
    normalised away so every style got the same beat, and only geometry
    survived. Each must still differ from every other in what it emphasises."""
    from lyricfield.types.lyric_grid.params import Params, backdrop_from

    seen = {}
    for st in BACKABLE:
        p = Params()
        backdrop_from(p, st.params)
        b = p.backdrop
        seen[st.slug] = (round(b.back_wave, 2), round(b.back_kick, 2),
                         round(b.back_snare, 2), round(b.back_high, 2),
                         round(b.back_density, 2))
    assert len(set(seen.values())) == len(seen), f"looks collapsed: {seen}"


def test_the_kick_led_look_is_still_kick_led():
    from lyricfield.types.lyric_grid.params import Params, backdrop_from
    p = Params()
    backdrop_from(p, S.get_style("heartbeat", type="pulse_grid").params)
    assert p.backdrop.back_kick > p.backdrop.back_wave * 3, (
        "heartbeat is 'the kick is the whole picture'; it must not arrive as a sweep")


def test_the_hat_led_look_keeps_its_hats():
    from lyricfield.types.lyric_grid.params import Params, backdrop_from
    p = Params()
    backdrop_from(p, S.get_style("shimmer", type="pulse_grid").params)
    assert p.backdrop.back_high > p.backdrop.back_wave, (
        "shimmer has no sweep; the hats and snare carry it")


def test_a_beatsync_style_brings_its_own_colour():
    """Per the decision: the tile you clicked is what lands."""
    from lyricfield.types.lyric_grid.params import Params, backdrop_from
    p = Params()
    st = S.get_style("heartbeat", type="pulse_grid")
    backdrop_from(p, st.params)
    assert p.backdrop.back_hue == st.params.look.dim_hue


def test_no_backdrop_clears_it(tmp_path):
    ws = Workspace.create("No backdrop", root=tmp_path, copy_source=False)
    run_mod._honour_pick(_ctx(ws, back_type="pulse_grid", back_style="sweep"),
                         lambda m: None)
    assert ws.load_config().backdrop.back_level > 0
    run_mod._honour_pick(_ctx(ws, back_type="", back_style=""), lambda m: None)
    assert ws.load_config().backdrop.back_level == 0


def test_an_unknown_backdrop_is_reported_rather_than_applied(tmp_path):
    ws = Workspace.create("Unknown backdrop", root=tmp_path, copy_source=False)
    said = []
    changed = run_mod._honour_pick(
        _ctx(ws, back_type="nonsense", back_style=""), said.append)
    assert "backdrop" not in changed
    assert any("no video type" in m for m in said), said


def test_the_backdrop_gives_way_when_brightness_does(tmp_path):
    """The backdrop is bounded by the band the ambient decoration occupies, and
    the Brightness control moves that band. Whatever it is pulled to, the words
    must still be the brightest thing and the config must stay valid."""
    from lyricfield.types.lyric_grid import params as P

    p = P.Params()
    P.backdrop_from(p, S.get_style("shimmer", type="pulse_grid").params)
    assert p.backdrop.back_level + p.backdrop.back_lift <= p.look.level_max + 1e-9

    P.apply_control(p, "brightness", 0.0)          # the dimmest setting there is
    assert p.validate() == [], p.validate()
    assert p.backdrop.back_level + p.backdrop.back_lift <= p.look.level_max + 1e-9


def test_clamping_is_reported_rather_than_silent():
    """`reconcile` runs before `validate`, so a backdrop can never fail -- it is
    quietly clipped instead. A look rendered at half strength with nothing said
    is the defect class this project keeps closing."""
    from lyricfield.types.lyric_grid import params as P

    p = P.Params()
    p.look.level_min = p.look.level_max = 0.02     # almost no room at all
    clamped = P.backdrop_from(p, S.get_style("shimmer", type="pulse_grid").params)
    assert clamped, "nothing reported although the budget could not hold it"
    assert any("words stay readable" in c for c in clamped)


# ------------------------------------------------------------------- the UI

def test_the_ui_sends_the_selected_type_with_the_run():
    body = re.search(r"function runBody\(extra\) \{(.+?)\n\}", INDEX.read_text(), re.S)
    assert body, "runBody() is gone or was renamed"
    assert "type:" in body.group(1), "runBody() does not send the renderer"
    assert "back_type:" in body.group(1), "runBody() does not send the backdrop"


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
