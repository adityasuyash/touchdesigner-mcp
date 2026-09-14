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
        "frames": 0, "motion": 0.0, "mean": 0.0, "moving": False,
        "peak": 0.0, "lit": 0.0}


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


def test_every_beatsync_look_has_a_preview_of_it_behind_words():
    """Its own preview was captured as the whole picture, at a brightness and
    density it is not allowed behind lyrics -- so the tile would promise
    something the render cannot deliver."""
    from lyricfield.types.lyric_grid.params import can_back_words
    # Only the looks that share the grid's field; see test_run_pick for why a
    # renderer with its own network cannot be another one's ambient layer.
    beat = [st for st in SHIPPED
            if types_mod.get_type(st.type).family == types_mod.BEATSYNC
            and can_back_words(st.params)]
    if not BACKDROP_ROOT.exists():
        pytest.skip("no backdrop previews on this machine")
    # Keyed by BOTH renderers: the layer is a property of the pair. Keyed on
    # the beat style's slug alone, `_backdrops/lyric_grid/tide` stood for "the
    # backdrop for some style called tide", one same-named style away from two
    # tiles sharing one video.
    missing = [f"{st.type}/{st.slug}" for st in beat
               if not (BACKDROP_ROOT / types_mod.DEFAULT_TYPE / st.type
                       / st.slug / "preview.mp4").exists()]
    assert not missing, f"no behind-the-words preview for: {missing}"


def test_the_backdrop_previews_differ_from_the_standalone_ones():
    """If they were the same file the whole point would be lost."""
    import hashlib
    from lyricfield.types.lyric_grid.params import can_back_words
    # Only the looks that share the grid's field; see test_run_pick for why a
    # renderer with its own network cannot be another one's ambient layer.
    beat = [st for st in SHIPPED
            if types_mod.get_type(st.type).family == types_mod.BEATSYNC
            and can_back_words(st.params)]
    if not BACKDROP_ROOT.exists():
        pytest.skip("no backdrop previews on this machine")
    for st in beat:
        behind = (BACKDROP_ROOT / types_mod.DEFAULT_TYPE / st.type
                  / st.slug / "preview.mp4")
        alone = st.preview_video(ROOT)
        if not (behind.exists() and alone.exists()):
            continue
        assert hashlib.md5(behind.read_bytes()).digest() != \
            hashlib.md5(alone.read_bytes()).digest(), st.slug


# ------------------------------------------------- a preview with words in it

LYRIC_PREVIEWS = [st for st in SHIPPED
                  if types_mod.get_type(st.type).needs_lyrics]


@pytest.mark.ffmpeg
def test_peak_is_measured_at_full_resolution(media):
    """A white word on black averages away when the frame is scaled down.

    The 96px thumbnail the motion measure works from turned a pixel-perfect
    white glyph into mid-grey, which is exactly the difference between "a word
    lit" and "the field drifted", so the peak has to be asked at native size.
    """
    out = media / "thin_white_line.mp4"
    if not out.exists():
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "color=black:size=240x240:rate=10:duration=2",
             "-vf", "geq=lum='if(lt(mod(X,24),1)*between(T,0.5,1.5),255,0)'"
                    ":cb=128:cr=128",
             "-pix_fmt", "yuv420p", str(out)],
            check=True)
    small = R.measure_motion(out)
    native = R.measure_motion(out, peak_width=240)
    assert native["peak"] > small["peak"], (
        f"scaling did not dim the line: {native['peak']} vs {small['peak']}")
    assert native["peak"] >= S.BOLD_PEAK


# Spotlight failed this for a while, at a peak of 0.55 where the other four
# lyric_grid styles reached 0.855 to 1.00, and the cause turned out to have
# nothing to do with the style: `styles._scratch_network` builds a preview with
# `push=False`, and text calibration used to hang off `push`, so the glyphs in
# every preview of a grid renderer sat on the font's natural 39.6px pitch while
# the weights that light them sat on the grid's 53.3px. For a style whose words
# sit low in the frame the two never met -- measured, the bold layer was exactly
# zero at every frame while both its inputs peaked at 1.0.
#
# See tests/test_calibration_container.py, which pins the fix. Spotlight now
# measures 0.937.
@pytest.mark.ffmpeg
@pytest.mark.parametrize("st", LYRIC_PREVIEWS, ids=[s.slug for s in LYRIC_PREVIEWS])
def test_a_lyric_preview_actually_lights_a_word(st):
    """The one thing a lyric preview exists to show.

    Every lyric preview shipped without a single lit pixel in it: they were
    parked at the busiest *drum* window, which on a real song is minutes past
    the last placeholder cue, and `styles.PREVIEW_CUES` stops at 7.5s. Motion
    passed them all, because the ambient field drifts whether or not a word is
    being sung.
    """
    video = st.preview_video(ROOT)
    if not video.exists():
        pytest.skip(f"{st.slug} has no preview recorded")
    m = R.measure_motion(video, peak_width=240)
    assert m["peak"] >= S.BOLD_PEAK, (
        f"{st.slug}: peak {m['peak']:.2f} never reaches the bold layer's "
        f"{S.BOLD_PEAK}; re-record with scripts/seed_styles.py --preview")


def test_a_preview_parked_away_from_the_words_is_refused_before_rendering():
    """Arithmetic, not a render.

    The wordless previews cost a TouchDesigner capture each before anything
    noticed, and nothing ever did -- they shipped. Whether a placeholder word is
    sung in the window is known from the cue table alone, so it is asked first
    and with no client at all.
    """
    st = next(s for s in SHIPPED if types_mod.get_type(s.type).needs_lyrics)
    with pytest.raises(S.WordlessPreview) as e:
        S.capture_preview(None, st, at=56.61, seconds=4.0)
    assert "56.6" in str(e.value)


def test_a_preview_over_the_words_gets_past_that_check():
    """The same call at a moment the placeholder cues cover must not be refused
    for this reason -- it has to get far enough to need a client."""
    st = next(s for s in SHIPPED if types_mod.get_type(s.type).needs_lyrics)
    with pytest.raises(Exception) as e:
        S.capture_preview(None, st, at=3.55, seconds=4.0)
    assert not isinstance(e.value, S.WordlessPreview), str(e.value)


# ----------------------------------------- a preview of the look it is of

def test_a_style_fingerprints_the_look_its_preview_was_recorded_from():
    """Nothing bound a preview to its parameters. `seed_styles` skipped on the
    file merely existing and the only test was that it moves, so re-tuning a
    look silently kept the video of the look it used to be -- the same class of
    lie as a still preview, and harder to notice.
    """
    import copy
    # A copy: `SHIPPED` is module-level and shared with every parametrised test
    # below it, so mutating it here made one of those fail with a stale look.
    st = copy.deepcopy(SHIPPED[0])
    before = st.fingerprint()
    assert len(before) == 16
    look = getattr(st.params, "look", None)
    assert look is not None
    look.glow = round(look.glow + 0.17, 4)
    assert st.fingerprint() != before, (
        "the fingerprint did not follow a change to the look")


@pytest.mark.parametrize("st", SHIPPED, ids=[s.slug for s in SHIPPED])
def test_every_shipped_preview_is_of_the_look_beside_it(st):
    if not st.preview_video(ROOT).exists():
        pytest.skip(f"{st.slug} has no preview recorded")
    assert st.preview_is_current(ROOT), (
        f"{st.slug}'s preview was recorded from different parameters; "
        f"re-record it with scripts/seed_styles.py --preview")


# --------------------------------- a preview of the look, not of the defaults

def test_a_preview_whose_script_cannot_read_its_params_is_refused():
    """The failure that shipped seven identical black tiles.

    `sync` writes the params DAT as a Python module and the eight newer
    renderers parse it as JSON, so for months the two halves of the system
    could not read each other's writing -- and nothing said so, because a field
    script that cannot read its params falls back to the defaults compiled into
    it and draws a plausible picture. Every style of that renderer then
    previews as the same video.

    `capture_preview` now asks the running script whether it made anything of
    what was written, and refuses rather than recording the defaults.
    """
    class _Client:
        def run(self, code, *a, **k):
            return ""

        def write(self, path, text):
            return None

        def call(self, *a, **k):
            raise AssertionError("a render was started despite unreadable params")

    st = next(s for s in SHIPPED if types_mod.get_type(s.type).needs_lyrics)
    import lyricfield.sync as sync_mod

    # The network build is somebody else's test; stand it aside so what is
    # under test here is the question asked after the push.
    saved = (S._scratch_network, S._drop_scratch, sync_mod.params_were_read)
    S._scratch_network = lambda client, cfg, say: "/project1/_preview"
    S._drop_scratch = lambda client: None
    sync_mod.params_were_read = lambda client, container=None: False
    try:
        with pytest.raises(S.FallbackPreview) as e:
            S.capture_preview(_Client(), st, at=3.55, seconds=4.0, live=None)
    finally:
        S._scratch_network, S._drop_scratch, sync_mod.params_were_read = saved
    assert "defaults" in str(e.value)


def test_refusing_a_fallback_preview_is_not_worth_retrying():
    """`seed_styles` walks a list of moments and retries `StillPreview` at each.
    A script that cannot read its params draws the same wrong picture at every
    moment, so this one must not be caught by that loop."""
    assert not issubclass(S.FallbackPreview, S.StillPreview)


# How different two previews have to be to be different pictures, as the mean
# frame-to-frame difference over the BRIGHTER of the two. Relative, because an
# absolute floor cannot work here: these previews span a mean luma of 0.15 to
# 59 of 255, so two near-black clips differ by less in absolute terms than two
# bright ones do when nothing is wrong. Measured on both populations -- the
# seven identical backdrops topped out at 0.106, and the lowest honest pair in
# the gallery (scope's Smoke and Trace, two looks of one renderer) is 0.137.
SAME_PICTURE = 0.12


def _difference(a, b):
    """Mean frame-to-frame difference between two clips, over the brighter."""
    import numpy as np

    n = min(len(a), len(b))
    d = float(np.abs(a[:n] - b[:n]).mean())
    return d / max(float(a.mean()), float(b.mean()), 1e-6)


@pytest.mark.ffmpeg
def test_the_backdrop_previews_are_not_all_the_same_video():
    """The user-visible symptom, asked directly.

    Seven tiles in the gallery showed the identical clip because every one of
    them was a recording of `lyric_grid`'s compiled-in defaults. Pairwise
    difference then was 0.0002; between honest previews of different looks it
    is two orders of magnitude larger.
    """
    import itertools

    import numpy as np

    vids = _backdrop_previews()
    if len(vids) < 2:
        pytest.skip("fewer than two backdrop previews on this machine")
    frames = {}
    for v in vids:
        a = R._gray_frames(v, 90)
        if a is None:
            pytest.skip(f"{v} could not be decoded")
        frames[v] = a[:16]
    worst = min((_difference(frames[a], frames[b]), a.parent.name, b.parent.name)
                for a, b in itertools.combinations(vids, 2))
    assert worst[0] > SAME_PICTURE, (
        f"{worst[1]} and {worst[2]} are the same picture "
        f"(difference {worst[0]:.3f} of their own brightness)")


@pytest.mark.ffmpeg
def test_no_two_previews_in_the_gallery_are_the_same_video():
    """The complaint that started this, asked as a measurement.

    "All the lyric styles look the same" and "the beatsync previews look the
    same" were both true, and for a reason no amount of re-tuning would have
    fixed: the field script could not read the params it was handed, so every
    style of a renderer previewed as that renderer's compiled-in defaults.
    Measured on both populations, as a share of the pictures' own brightness:
    the seven identical backdrops never exceeded 0.106, and the closest honest
    pair in the gallery is 0.137.
    """
    import itertools

    import numpy as np

    vids = sorted(ROOT.rglob("preview.mp4"))
    if len(vids) < 2:
        pytest.skip("no previews on this machine")
    frames = {}
    for v in vids:
        a = R._gray_frames(v, 90)
        if a is not None:
            frames[v] = a[:16]
    same = []
    for a, b in itertools.combinations(sorted(frames), 2):
        d = _difference(frames[a], frames[b])
        if d <= SAME_PICTURE:
            same.append(f"{a.relative_to(ROOT)} and {b.relative_to(ROOT)} "
                        f"(difference {d:.3f} of their own brightness)")
    assert not same, "previews that are the same picture:\n  " + "\n  ".join(same)
