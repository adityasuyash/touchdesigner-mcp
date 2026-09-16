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
    """The gallery groups looks by renderer, so one renderer's looks would make
    every tile a variation of one picture."""
    renderers = {st.type for st in SHIPPED}
    assert len(renderers) > 1, f"every shipped look is {renderers}"


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


# Two tests about backdrop previews lived here. A beat look is not a picture
# behind the words any more, so there is no such capture to compare.


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
    S._scratch_network = (lambda client, cfg, say, with_beat=False:
                          ("/project1/_preview", "/project1/_preview/words"))
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

    # `_beat/` is left out deliberately; it has its own check below. A beat
    # preset IS the same picture as the next one at rest -- that is what it is,
    # an effect on somebody else's look -- and differs only in the frames after
    # a hit. An average over sixteen frames dilutes precisely the event that
    # distinguishes it: measured on the reference captures, Punch against None
    # averages 0.055 and peaks at 25.7. For these the question is the peak.
    vids = [v for v in sorted(ROOT.rglob("preview.mp4"))
            if "_beat" not in v.parts]
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


# ------------------------------------------- a renderer is not its own style

def test_a_renderer_ships_a_tile_of_its_own_only_when_it_ships_no_looks():
    """A look is a preset of its renderer, so the two can only resemble each
    other. Showing both put every renderer on screen two to six times as
    near-identical pictures -- Approach beside Corridor and Flyby, Orbit beside
    Ring, Window beside Tide -- and fifteen renderers became fifty-three tiles.

    So: where a renderer has looks, those ARE its tiles; where it has none, it
    gets one of its own. This is the rule the gallery follows, checked here
    because the next batch of looks would otherwise bring the duplicates back.
    """
    owned = {st.type for st in SHIPPED}
    builtin = {d.parent.name for d in (ROOT / "_builtin").glob("*/*")
               if d.is_dir()}
    both = sorted(owned & builtin)
    assert not both, (
        f"these renderers ship a built-in tile AND looks, so the gallery shows "
        f"the same picture twice: {both}")


def test_every_renderer_reaches_the_gallery_exactly_once_over():
    """The other half: no renderer may vanish. Dropping a built-in tile is only
    safe because its looks stand in for it."""
    owned = {st.type for st in SHIPPED}
    builtin = {d.parent.name for d in (ROOT / "_builtin").glob("*/*")
               if d.is_dir()}
    missing = [vt.slug for vt in types_mod.list_types()
               if vt.slug not in owned and vt.slug not in builtin]
    assert not missing, f"renderers with no tile at all: {missing}"


def test_no_two_tiles_in_a_row_share_a_display_name():
    """Two tiles reading "Static" or "Tide" in one row is the duplicate the
    caption disambiguation exists to soften. With one tile per look there is
    nothing left to disambiguate, and it should stay that way."""
    import collections
    names = [st.name for st in SHIPPED]
    dupes = [n for n, c in collections.Counter(names).items() if c > 1]
    assert not dupes, f"the row has two tiles called {dupes}"


# ------------------------------------------------- the frame that was asked for

@pytest.mark.ffmpeg
def test_a_still_comes_from_the_frame_it_was_asked_for(tmp_path):
    """`-ss` before `-i` is an input seek and lands on a keyframe.

    It looks right on any single clip and is only exposed by comparing two
    encodes of the same thing at the same timestamp -- which is exactly what a
    row of beat-preset tiles does. `none` and `punch`, identical four-second
    renders cut at the same frames, came back showing DIFFERENT WORDS at
    1.79s, because their encoders had placed keyframes differently. The stills
    said the effect changed the lyrics.

    A fixture with a known value per frame has the ground truth a real
    recording cannot give: frame n is grey n, so the still says which frame it
    is.
    """
    import subprocess

    import numpy as np

    from lyricfield import render as render_mod

    src = tmp_path / "ramp.mp4"
    # 48 frames at 24fps, frame n a flat grey of 4n. Long GOP on purpose, so an
    # input seek has somewhere wrong to land.
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "color=c=black:s=64x64:r=24:d=2",
         "-vf", "geq=lum='4*N':cb=128:cr=128",
         "-c:v", "libx264", "-g", "48", "-pix_fmt", "yuv420p", str(src)],
        check=True)

    frames = render_mod._gray_frames(src, 64)
    assert frames is not None and len(frames) >= 40

    for n in (5, 17, 33):
        out = render_mod.still_at(src, n / 24.0, tmp_path / f"{n}.png")
        got = render_mod._gray_frames(out, 64)
        assert got is not None
        # Within one frame's worth of grey, and nowhere near the keyframe at 0.
        assert abs(float(got[0].mean()) - float(frames[n].mean())) < 6.0, (
            f"frame {n}: still reads {got[0].mean():.1f}, "
            f"the frame reads {frames[n].mean():.1f}")


def test_nothing_pulls_a_still_with_an_input_seek():
    """The class, not the instance. Three places extracted stills and all three
    seeked before `-i`; they now go through `render.still_at`."""
    import re
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    offenders = []
    for py in list((repo / "lyricfield").rglob("*.py")) + \
            list((repo / "scripts").rglob("*.py")):
        src = py.read_text(encoding="utf-8")
        for call in re.findall(r"\[[^\[\]]*?\"ffmpeg\".*?\]", src, re.S):
            if "frames:v" not in call:
                continue            # an audio seek; accurate enough, not this
            if '"-ss"' in call and call.index('"-ss"') < call.index('"-i"'):
                offenders.append(f"{py.relative_to(repo)}: {call[:70]}...")
    assert not offenders, "\n".join(offenders)


# In 0-255 luma. The presets now answer a beat on a reference that does not,
# over a word that is held still, so the difference from the baseline IS the
# effect, everywhere, with nothing to mask.
BEAT_SHOWS = 5.0

# And how flat the baseline has to be. It is a renderer with its own beat
# response switched off, showing one held word: nothing in it should move.
# Before that, it flashed -- `monument` lifts the whole frame by `kick_lift` on
# every kick, so the tile that shows NO effect went from a frame mean of 7.6 to
# 16.1 four times in four seconds, identically in all five tiles. That flash
# was the loudest thing in every one of them, and the complaint was that the
# previews "show just flashes to represent the kick hit and not what the
# beatsync style actually does".
BASELINE_FLAT = 2.0


@pytest.mark.ffmpeg
def test_the_beat_reference_does_nothing_on_its_own():
    """The check that would have caught the flash.

    Everything else in this file measures presets against the baseline, so
    anything the baseline does cancels out and is invisible to them -- which is
    exactly how a reference renderer flashing on every kick survived two rounds
    of "why do these all look the same".
    """
    import numpy as np

    from lyricfield import beat as beat_mod

    base = ROOT / beat_mod.PREVIEW_DIR / beat_mod.REFERENCE / "none" / "preview.mp4"
    if not base.exists():
        pytest.skip("the beat previews are not recorded on this machine")
    b = R._gray_frames(base, 90)
    assert b is not None and len(b) >= 60

    step = np.abs(np.diff(b, axis=0)).mean(axis=(1, 2))
    worst = float(step.max())
    swing = float(b.mean(axis=(1, 2)).max() - b.mean(axis=(1, 2)).min())
    assert worst < BASELINE_FLAT, (
        f"the baseline moves by {worst:.2f} between frames (mean brightness "
        f"swings {swing:.2f} over the clip). The tile that shows no effect has "
        "to show no effect, or every preset is read against it doing something")


@pytest.mark.ffmpeg
def test_every_beat_preset_visibly_moves_the_words():
    """Each preset against the unaffected baseline.

    Three versions of this check have passed on previews that showed nothing or
    showed the wrong thing, and each failure is worth naming because the shape
    of the test changed to answer it. The first took the peak over the whole
    clip, and word-transition jitter between two encodes cleared its threshold
    while every envelope in the capture was zero. The second masked the word
    changes, and the mask also covered the reference renderer's own kick
    response -- hiding the frames the effect lives in. The answer to both was
    to stop measuring around the noise and remove it: one word, held, on a
    reference that does nothing.
    """
    import numpy as np

    from lyricfield import beat as beat_mod

    root = ROOT / beat_mod.PREVIEW_DIR / beat_mod.REFERENCE
    base = root / "none" / "preview.mp4"
    if not base.exists():
        pytest.skip("the beat previews are not recorded on this machine")
    b = R._gray_frames(base, 90)
    assert b is not None

    quiet = []
    for slug, name, _why, _v in beat_mod.PRESETS:
        if slug == "none":
            continue
        v = root / slug / "preview.mp4"
        if not v.exists():
            quiet.append(f"{name}: no preview recorded")
            continue
        a = R._gray_frames(v, 90)
        n = min(len(a), len(b))
        peak = float(np.abs(a[:n] - b[:n]).mean(axis=(1, 2)).max())
        if peak < BEAT_SHOWS:
            quiet.append(f"{name}: peaks {peak:.2f} against the baseline")
    assert not quiet, (
        "presets that do not show (an empty drum table looks exactly like "
        "this):\n  " + "\n  ".join(quiet))


@pytest.mark.ffmpeg
def test_no_two_beat_presets_are_the_same_recording():
    """Not just "each differs from none" -- each has to differ from the others.

    With no drum table every preset is the zoom's idle breathe scaled by its
    own travel, so they differ from `none` by a little and from each other by
    almost nothing. Comparing only against the baseline cannot see that.
    """
    import itertools

    import numpy as np

    from lyricfield import beat as beat_mod

    root = ROOT / beat_mod.PREVIEW_DIR / beat_mod.REFERENCE
    if not (root / "none" / "preview.mp4").exists():
        pytest.skip("the beat previews are not recorded on this machine")

    have = {}
    for slug, name, _why, _v in beat_mod.PRESETS:
        if slug == "none":
            continue
        v = root / slug / "preview.mp4"
        if v.exists():
            have[name] = R._gray_frames(v, 90)
    same = []
    for (an, a), (bn, b) in itertools.combinations(sorted(have.items()), 2):
        n = min(len(a), len(b))
        peak = float(np.abs(a[:n] - b[:n]).mean(axis=(1, 2)).max())
        if peak < BEAT_SHOWS:
            same.append(f"{an} and {bn} peak {peak:.2f} apart")
    assert not same, "presets recorded as the same picture:\n  " + "\n  ".join(same)


# ------------------------------------------ a beat preview with nothing in it

def _stub_capture(monkeypatched):
    """A client and a stood-aside network, for the checks made after the push."""
    class _Client:
        def run(self, code, *a, **k):
            return ""

        def write(self, path, text):
            return None

        def call(self, *a, **k):
            raise AssertionError("a render was started despite the refusal")

    return _Client()


def test_a_beat_preview_with_no_drum_hits_is_refused():
    """The failure that shipped five identical tiles.

    The drum table never reached `fx_drive`: `capture_preview` looked the
    workspace up by title where a slug was wanted, and wrote the table to the
    renderer's container while the driver reads its own. Both failures were
    silent -- an empty table does not raise, `_last` returns -1e9 and every
    envelope clamps to 0.0 -- so five presets recorded as five copies of the
    zoom's idle breathe and passed every check there was.
    """
    import lyricfield.sync as sync_mod
    from lyricfield import beat as beat_mod

    st = next(s for s in SHIPPED if types_mod.get_type(s.type).needs_lyrics)
    saved = (S._scratch_network, S._drop_scratch,
             sync_mod.params_were_read, sync_mod.drums_were_read)
    S._scratch_network = (lambda client, cfg, say, with_beat=False:
                          ("/project1/_preview", "/project1/_preview/words"))
    S._drop_scratch = lambda client: None
    sync_mod.params_were_read = lambda client, container=None: True
    sync_mod.drums_were_read = (lambda client, container=None:
                                {"kick": 0, "snare": 0, "hat": 0})
    try:
        with pytest.raises(S.BeatlessPreview) as e:
            S.capture_preview(_stub_capture(None), st, at=3.55, seconds=4.0,
                              live=None, with_beat=True,
                              beat=beat_mod.preset("punch"))
    finally:
        (S._scratch_network, S._drop_scratch,
         sync_mod.params_were_read, sync_mod.drums_were_read) = saved
    assert "no drum hits" in str(e.value)


def test_the_none_preset_is_allowed_to_have_nothing_to_answer():
    """It switches every effect off, and it is the baseline the whole row is
    read against. Refusing it would leave the comparison nothing to compare to.

    Asserted as "whatever stops this capture, it is not the beat check" rather
    than by running it to completion: the stub has no timeline, so it gets as
    far as the seek and no further, and how far that is is not this test's
    business.
    """
    import lyricfield.sync as sync_mod
    from lyricfield import beat as beat_mod

    st = next(s for s in SHIPPED if types_mod.get_type(s.type).needs_lyrics)
    saved = (S._scratch_network, S._drop_scratch,
             sync_mod.params_were_read, sync_mod.drums_were_read)
    S._scratch_network = (lambda client, cfg, say, with_beat=False:
                          ("/project1/_preview", "/project1/_preview/words"))
    S._drop_scratch = lambda client: None
    sync_mod.params_were_read = lambda client, container=None: True
    sync_mod.drums_were_read = (lambda client, container=None:
                                {"kick": 0, "snare": 0, "hat": 0})
    try:
        with pytest.raises(Exception) as e:
            S.capture_preview(_stub_capture(None), st, at=3.55, seconds=4.0,
                              live=None, with_beat=True,
                              beat=beat_mod.preset("none"))
    finally:
        (S._scratch_network, S._drop_scratch,
         sync_mod.params_were_read, sync_mod.drums_were_read) = saved
    assert not isinstance(e.value, S.BeatlessPreview), \
        "the none preset was refused for having no beat to answer"


def test_refusing_a_beatless_preview_is_not_worth_retrying():
    """The seeder walks a list of moments on `StillPreview`. An empty drum
    table is empty at every moment, so this must not send it round that loop."""
    assert not issubclass(S.BeatlessPreview, S.StillPreview)
