"""Every preview a tile asks for must exist.

This is the test whose absence let "28 styles, every one with a preview" be
reported while six of thirteen beatsync tiles were dead. The check that existed
asked whether `styles/<type>/<slug>/preview.mp4` was on disk. The gallery does
not request that URL for a beatsync tile: it rewrites it to a backdrop path
built from the *picked lyric renderer*, and sets `shown = true` regardless of
whether such a file could exist.

So this walks the payloads the way the client does, for every pick a person can
make, and asserts the URL actually resolves.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from lyricfield import styles as styles_mod
from lyricfield import types as types_mod

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "styles"

SHIPPED = styles_mod.list_styles(ROOT)
LYRIC_TYPES = [t for t in types_mod.list_types() if t.family == types_mod.LYRIC]
BEAT_STYLES = [st for st in SHIPPED
               if types_mod.get_type(st.type).family == types_mod.BEATSYNC]


def _served(url: str) -> Path:
    """Where the `/styles` mount would look for this URL."""
    assert url.startswith("/styles/"), url
    return ROOT / url[len("/styles/"):]


def _tile_preview(st, picked_lyric):
    """The preview URL the gallery would request for this tile.

    Mirrors `styleCard()`; kept deliberately in this shape so the test breaks
    if the client's rule changes and this is not updated with it.
    """
    from lyricfield.ui import server as srv

    d = srv.style_payload(st)
    fam = d["family"]
    if fam == "beatsync" and picked_lyric:
        back = d.get("backdrop_preview")
        if back:
            return back
    return d["preview"] if d.get("has_preview") else None


@pytest.mark.parametrize("picked", [t.slug for t in LYRIC_TYPES] + [""],
                         ids=[t.slug for t in LYRIC_TYPES] + ["no-lyric-pick"])
def test_no_beatsync_tile_requests_a_preview_that_is_not_there(picked):
    """With `lyric_grid` picked, six of thirteen beatsync tiles asked for a
    backdrop that is only ever generated for pulse_grid and swell. With any of
    the five newer lyric renderers picked, all thirteen did, because
    `_backdrops/<that renderer>/` does not exist at all.
    """
    missing = []
    for st in BEAT_STYLES:
        url = _tile_preview(st, picked)
        if url is None:
            continue                     # "no preview yet" is an honest answer
        if not _served(url).exists():
            missing.append(f"{st.type}/{st.slug} -> {url}")
    assert not missing, (
        f"with {picked or 'no lyric renderer'} picked, these tiles request a "
        f"preview that is not on disk: {missing}")


@pytest.mark.parametrize("st", SHIPPED, ids=[f"{s.type}-{s.slug}" for s in SHIPPED])
def test_every_style_tile_resolves(st):
    """The lyric row, and the beatsync row with nothing picked."""
    url = _tile_preview(st, "")
    if url is None:
        pytest.skip(f"{st.type}/{st.slug} has no preview recorded")
    assert _served(url).exists(), f"{st.type}/{st.slug} -> {url}"


def test_every_builtin_tile_resolves():
    """The renderer-default tiles the gallery synthesises client-side."""
    from lyricfield.ui import server as srv

    missing = []
    for t in types_mod.list_types():
        d = srv.type_payload(t)
        if not d.get("has_preview"):
            continue
        url = f"/styles/_builtin/{t.slug}/{t.slug}/preview.mp4"
        if not _served(url).exists():
            missing.append(url)
    assert not missing, f"built-in tiles requesting a missing preview: {missing}"


def test_a_poster_exists_beside_every_preview_a_tile_asks_for():
    """The tile mounts `<img src=poster>` derived by swapping the extension, so
    a preview with no poster is a broken image even when the video is there."""
    missing = []
    for picked in [t.slug for t in LYRIC_TYPES] + [""]:
        for st in SHIPPED:
            url = _tile_preview(st, picked)
            if url is None:
                continue
            poster = _served(url.replace(".mp4", ".png"))
            if not poster.exists():
                missing.append(str(poster.relative_to(ROOT)))
    assert not missing, f"previews with no poster beside them: {sorted(set(missing))}"


# --------------------------------------------- a style is (renderer, slug)

def test_every_style_resolves_to_itself():
    """A style's identity is `(type, slug)` -- that is how it is filed on disk,
    and two renderers may honestly both have a "Tide"."""
    for st in SHIPPED:
        got = styles_mod.get_style(st.slug, ROOT, type=st.type)
        assert (got.type, got.slug) == (st.type, st.slug)


def test_a_slug_two_renderers_share_is_refused_rather_than_guessed():
    """It used to return the first match, so `get_style("tide")` was always
    swell's and `window/tide` could not be reached at all. Worse, `run` takes
    the resolved style's type as the renderer to use -- so a bare slug could
    quietly change which renderer you got.
    """
    from collections import Counter
    dupes = [slug for slug, n in Counter(s.slug for s in SHIPPED).items() if n > 1]
    if not dupes:
        pytest.skip("no two shipped styles share a slug right now")
    with pytest.raises(styles_mod.AmbiguousStyle):
        styles_mod.get_style(dupes[0], ROOT)


def test_a_slug_only_one_renderer_has_still_resolves_bare():
    """The refusal is about ambiguity, not about requiring a type everywhere."""
    from collections import Counter
    counts = Counter(s.slug for s in SHIPPED)
    unique = next(s for s in SHIPPED if counts[s.slug] == 1)
    assert styles_mod.get_style(unique.slug, ROOT).type == unique.type


def test_deleting_by_an_ambiguous_slug_is_refused(tmp_path):
    """`delete_style` calls `shutil.rmtree`. On a slug two renderers share it
    used to remove whichever sorted first -- the wrong directory, permanently.
    """
    from collections import Counter
    dupes = [slug for slug, n in Counter(s.slug for s in SHIPPED).items() if n > 1]
    if not dupes:
        pytest.skip("no two shipped styles share a slug right now")
    with pytest.raises(styles_mod.AmbiguousStyle):
        styles_mod.delete_style(dupes[0], ROOT)
    # and nothing was removed
    for st in SHIPPED:
        if st.slug == dupes[0]:
            assert st.dir(ROOT).exists()


# ------------------------------------- where a backdrop draft is filed

def test_a_backdrop_draft_is_the_lyric_renderer_but_filed_under_both():
    """`type` and `dir()` answer two different questions, and folding them into
    one broke every backdrop capture.

    A backdrop draft IS `lyric_grid`: those are its params, that is the field
    script that draws it, that is what needs words. But it is STORED under both
    renderers' slugs, so two beat styles sharing a name cannot collapse into one
    video. Writing the path into `type` instead made `Style.video_type` raise
    `no video type 'lyric_grid/pulse_grid'` before any capture could start.
    """
    st = styles_mod.Style(name="Heartbeat behind", slug="heartbeat", type="lyric_grid",
                 filed_under="lyric_grid/pulse_grid")
    assert st.video_type.slug == "lyric_grid"
    assert st.video_type.needs_lyrics is True
    assert st.dir("/tmp/x") == Path("/tmp/x/lyric_grid/pulse_grid/heartbeat")


def test_a_style_with_nothing_to_file_it_under_lives_under_its_type():
    """Every real style. `filed_under` is empty for all of them, so nothing
    about where a style is stored changed."""
    st = styles_mod.Style(name="Tide", slug="tide", type="swell")
    assert st.dir("/tmp/x") == Path("/tmp/x/swell/tide")


def test_two_beat_styles_sharing_a_name_get_different_backdrop_folders():
    """The reason the path is keyed by both. On the beat slug alone the second
    style never records at all, because the first already made the file."""
    a = styles_mod.Style(name="Tide behind", slug="tide", type="lyric_grid",
                filed_under="lyric_grid/swell")
    b = styles_mod.Style(name="Tide behind", slug="tide", type="lyric_grid",
                filed_under="lyric_grid/window")
    assert a.dir("/tmp/x") != b.dir("/tmp/x")


# ------------------------------------------------- a tile that says what it is

def test_every_tile_the_gallery_shows_carries_a_description():
    """The tooltip has nothing to show if the payload does not carry it.

    Twenty-seven tiles that can only be told apart by staring at a four-second
    loop is the complaint this answers, so an empty description is a tile that
    cannot explain itself.
    """
    import lyricfield.ui.server as srv

    bare = []
    for st in styles_mod.list_styles(srv.STYLES_ROOT):
        if not (srv.style_payload(st).get("description") or "").strip():
            bare.append(f"{st.type}/{st.slug}")
    for vt in types_mod.list_types():
        if not (srv.type_payload(vt).get("description") or "").strip():
            bare.append(vt.slug)
    assert not bare, f"tiles with nothing to say: {bare}"


def test_a_description_is_a_sentence_rather_than_a_label():
    """"Grid" tells you nothing you could not read off the caption. These are
    what the tooltip shows, so they have to add something."""
    short = []
    for st in styles_mod.list_styles(srv_root()):
        d = (st.description or "").strip()
        if len(d.split()) < 4:
            short.append(f"{st.type}/{st.slug}: {d!r}")
    assert not short, f"descriptions too thin to be worth a tooltip: {short}"


def srv_root():
    import lyricfield.ui.server as srv
    return srv.STYLES_ROOT
