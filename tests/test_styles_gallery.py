"""The shipped styles, and the guarantee that a preview shows something.

A style is only useful if the gallery can show what it looks like, and a
preview is only a preview if it moves -- a still frame of a beat renderer is
indistinguishable from a beat renderer that does not work. Five of them shipped
that way before any of this existed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from lyricfield import analysis as A
from lyricfield import render as R
from lyricfield import styles as S
from lyricfield import types as types_mod

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "styles"
SHIPPED = S.list_styles(ROOT)


# ------------------------------------------------------------ what ships

def test_there_are_styles_for_more_than_one_renderer():
    """Until there were, the gallery's beatsync row was unreachable dead code:
    it grouped the styles on disk, and every style on disk was a lyric one."""
    families = {types_mod.get_type(st.type).family for st in SHIPPED}
    assert len(families) > 1, f"every shipped style is {families}"


@pytest.mark.parametrize("st", SHIPPED, ids=[s.slug for s in SHIPPED])
def test_a_shipped_style_is_a_valid_config_of_its_type(st):
    """A style file predates the renderer it configures the moment either
    changes, and applying a stale one is how a render fails at the far end."""
    assert st.params.validate() == [], f"{st.slug}: {st.params.validate()}"


@pytest.mark.parametrize("st", SHIPPED, ids=[s.slug for s in SHIPPED])
def test_a_shipped_style_declares_every_section_its_type_has(st):
    """The first shipped style was missing six tunables and a whole section,
    including one the Glow control moves -- so that control changed something
    the style could not remember.

    This reads the TOML on disk, not `st.sections`. `Style.sections` reports the
    fields of the dataclass `build_sections` produced, and `build_sections`
    fills every missing section in from its defaults -- so the first version of
    this test compared a dataclass's fields with the same dataclass's fields and
    could never fail. It was written to catch exactly the thing it could not see.
    """
    import tomllib
    path = st.dir(ROOT) / "style.toml"
    on_disk = set(tomllib.loads(path.read_text())) - {"meta"}
    missing = sorted(set(types_mod.get_type(st.type).section_names()) - on_disk)
    assert not missing, (
        f"{st.slug}/style.toml has no {missing} section; re-save it with "
        "scripts/seed_styles.py rather than hand-patching")


@pytest.mark.parametrize("st", SHIPPED, ids=[s.slug for s in SHIPPED])
def test_a_shipped_style_actually_differs_from_its_type_defaults(st):
    """A style identical to the built-in is a second tile for the same look."""
    from lyricfield.sections import flatten
    default = flatten(types_mod.get_type(st.type).default_params())
    assert flatten(st.params) != default, f"{st.slug} is the defaults verbatim"


@pytest.mark.parametrize("st", SHIPPED, ids=[s.slug for s in SHIPPED])
def test_a_style_tells_the_gallery_which_family_it_belongs_to(st):
    """The gallery groups tiles by family and defaults a style with none to
    "lyric". Without this every beatsync look sat in the lyric row, under a
    heading promising words it does not draw."""
    d = st.to_dict(ROOT)
    assert d["family"] == types_mod.get_type(st.type).family


@pytest.mark.parametrize("st", SHIPPED, ids=[s.slug for s in SHIPPED])
def test_a_shipped_style_has_a_preview_that_moves(st):
    """Motion is what distinguishes one style from another; a still cannot
    show it, and a video that does not move is a still with extra steps."""
    video = st.preview_video(ROOT)
    if not video.exists():
        pytest.skip(f"{st.slug} has no preview on this machine")
    m = R.measure_motion(video)
    assert m["frames"] > 1, f"{st.slug}: {m}"
    assert m["moving"], f"{st.slug} preview is a still frame: {m}"


# ------------------------------------------------------- measuring motion

def test_a_still_video_is_reported_as_not_moving(black_mp4):
    m = R.measure_motion(black_mp4)
    assert m["frames"] > 1
    assert m["moving"] is False


def test_a_video_that_changes_is_reported_as_moving(flashes_mp4):
    m = R.measure_motion(flashes_mp4)
    assert m["moving"] is True
    assert m["motion"] > 0


def test_measuring_something_that_is_not_a_video_does_not_raise(tmp_path):
    junk = tmp_path / "notavideo.mp4"
    junk.write_bytes(b"not a container")
    assert R.measure_motion(junk) == {
        "frames": 0, "motion": 0.0, "mean": 0.0, "moving": False}


# -------------------------------------------------- choosing the moment

def test_the_busiest_window_lands_on_the_clicks(media, tmp_path):
    """Clicks in the middle third only: the window has to find them rather
    than take a fixed fraction of the duration, which is what put five
    previews on a stretch of silence."""
    out = tmp_path / "clustered.wav"
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
         "-i", "sine=frequency=60:duration=30",
         "-af", "volume='if(between(t,12,20)*lt(mod(t,0.5),0.05),1,0)':eval=frame",
         "-ac", "1", str(out)], check=True)
    at = A.busiest_window(out, seconds=4.0)
    assert 10.0 <= at <= 18.0, f"picked {at}s, nowhere near the clicks"


def test_a_track_shorter_than_the_window_starts_at_zero(sine_wav):
    assert A.busiest_window(sine_wav, seconds=600.0) == 0.0


def test_a_track_with_no_kicks_at_all_still_answers(sine_wav):
    """A steady tone has no events; the caller still needs a number."""
    at = A.busiest_window(sine_wav, seconds=1.0)
    assert at >= 0.0


# ------------------------------------------------ the backdrop previews

BACKDROP_ROOT = ROOT / "_backdrops"


def _backdrop_previews():
    return sorted(BACKDROP_ROOT.rglob("preview.mp4"))


def test_the_backdrop_previews_are_not_mistaken_for_styles():
    """They live under the styles tree so the existing mount serves them and
    the gitignore negation tracks them, but they are presets over one type's
    tunables, not styles -- `_style_dirs` yields only folders holding a
    `style.toml`, and none of these has one."""
    if not BACKDROP_ROOT.exists():
        pytest.skip("no backdrop previews on this machine")
    assert not list(BACKDROP_ROOT.rglob("style.toml"))
    assert not [st for st in S.list_styles(ROOT) if "_backdrops" in str(st.dir(ROOT))]


@pytest.mark.parametrize("video", _backdrop_previews(),
                         ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}")
def test_a_backdrop_preview_moves(video):
    m = R.measure_motion(video)
    assert m["frames"] > 1, m
    assert m["moving"], f"{video.parent.name} preview is a still frame: {m}"


def test_a_dark_clip_is_not_mistaken_for_a_failed_render(black_mp4):
    """`wait_for_container` used to require 50 KB, which is a proxy for "the
    moov atom landed" and a bad one: a valid 132-frame capture of words on
    black came to 8.5 KB and was thrown away as a broken render."""
    assert black_mp4.stat().st_size < 50_000
    assert R._finished(black_mp4) is True


def test_something_that_is_not_a_container_is_rejected(tmp_path):
    junk = tmp_path / "half-written.mp4"
    junk.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4000)
    assert R._finished(junk) is False
