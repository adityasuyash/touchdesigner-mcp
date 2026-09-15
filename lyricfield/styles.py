"""Named, reusable presets of a video type's tunables.

A style is everything that decides how a renderer *looks and moves*, with none of
the per-song facts. That split already exists in `Config`: `track` holds the song
and the type's params hold the look, so a style is a type's params plus a name,
and applying one is a section-wise copy that provably cannot reach the track.

A style belongs to exactly one type. The sections of `lyric_grid` describe a
character field and mean nothing to a waveform renderer, so styles are stored
per type and applying one across types is refused rather than silently partial.

    styles/<type>/<slug>/
        style.toml
        preview.mp4     a short loop -- drift, dissolve, ripple and twinkle are
        preview.png     all motion, and two styles can look identical frozen

Styles are tracked in the repo; they are the reusable output of the work, and so
are their previews. A lyric preview is rendered from the placeholder words in
`data/preview_cues.tsv` and a beatsync one has no words at all, so neither
carries anything of the song that happened to be loaded -- which is what makes
them shippable rather than remade on every machine.
"""

from __future__ import annotations

import re
import shutil
import tomllib
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

from . import types as types_mod
from .config import Config
from .sections import toml_value

DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "styles"

_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    s = _SLUG.sub("-", name.strip().lower()).strip("-")
    return s or "untitled"


@dataclass
class Style:
    name: str = "Untitled"
    slug: str = "untitled"
    type: str = types_mod.DEFAULT_TYPE
    description: str = ""
    created: str = ""
    source_song: str = ""
    params: object = None
    # Where this is FILED, when that is not the same question as which renderer
    # it is for. A backdrop draft is `lyric_grid` params -- that is what builds,
    # what needs lyrics, what the field script comes from -- but it is stored
    # under both renderers' slugs so that two beat styles sharing a name cannot
    # collapse into one video. Empty for every real style, which is filed under
    # its own type.
    filed_under: str = ""

    def __post_init__(self) -> None:
        if self.params is None:
            self.params = types_mod.get_type(self.type).default_params()

    @property
    def video_type(self):
        return types_mod.get_type(self.type)

    @property
    def sections(self) -> tuple[str, ...]:
        return tuple(f.name for f in fields(self.params))

    # ---------- conversion ----------

    @classmethod
    def from_config(cls, cfg: Config, name: str, description: str = "",
                    source_song: str = "") -> "Style":
        import copy
        return cls(
            name=name,
            slug=slugify(name),
            type=cfg.type,
            description=description,
            created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source_song=source_song,
            params=copy.deepcopy(cfg.params),
        )

    def apply_to(self, cfg: Config) -> Config:
        """Copy this style's params onto a config, leaving `track` untouched."""
        import copy
        if cfg.type != self.type:
            raise ValueError(
                f"style {self.slug!r} is for video type {self.type!r}, but the song "
                f"is set to {cfg.type!r}. Switch the song's type first — these "
                "tunables describe a different renderer."
            )
        cfg.params = copy.deepcopy(self.params)
        return cfg

    def as_config(self) -> Config:
        """A Config carrying this style and default (empty) track data."""
        return self.apply_to(Config(type=self.type))

    # ---------- io ----------

    def dir(self, root: str | Path = DEFAULT_ROOT) -> Path:
        return Path(root) / (self.filed_under or self.type) / self.slug

    def fingerprint(self) -> str:
        """A short hash of exactly the values this look sets.

        Nothing bound a preview to the parameters it was recorded from, so
        re-tuning a look kept the old video: `seed_styles` skips on the file
        merely existing, and the only test is that it moves. A stale preview is
        the same class of lie as a still one -- the tile promises something the
        render will not deliver -- and this is what lets it be noticed.
        """
        import hashlib

        parts = []
        for section in self.sections:
            for k, v in sorted(asdict(getattr(self.params, section)).items()):
                parts.append(f"{section}.{k}={v!r}")
        return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]

    def preview_is_current(self, root: str | Path = DEFAULT_ROOT) -> bool:
        """Is the preview on disk a recording of THIS look?"""
        video = self.preview_video(root)
        if not video.exists():
            return False
        stamp = self.dir(root) / "preview.fingerprint"
        if not stamp.exists():
            return False
        return stamp.read_text(encoding="utf-8").strip() == self.fingerprint()

    def stamp_preview(self, root: str | Path = DEFAULT_ROOT) -> None:
        """Record which look the preview beside it is of."""
        d = self.dir(root)
        d.mkdir(parents=True, exist_ok=True)
        (d / "preview.fingerprint").write_text(self.fingerprint() + "\n",
                                               encoding="utf-8")

    def save(self, root: str | Path = DEFAULT_ROOT) -> Path:
        d = self.dir(root)
        d.mkdir(parents=True, exist_ok=True)
        out = [
            "# lyricfield style. Reusable across songs; contains no song data.",
            "",
            "[meta]",
            f"name = {toml_value(self.name)}",
            f"slug = {toml_value(self.slug)}",
            f"type = {toml_value(self.type)}",
            f"description = {toml_value(self.description)}",
            f"created = {toml_value(self.created)}",
            f"source_song = {toml_value(self.source_song)}",
            "",
        ]
        for section in self.sections:
            out.append(f"[{section}]")
            for k, v in asdict(getattr(self.params, section)).items():
                out.append(f"{k} = {toml_value(v)}")
            out.append("")
        (d / "style.toml").write_text("\n".join(out), encoding="utf-8")
        return d

    @classmethod
    def load(cls, path: str | Path) -> "Style":
        path = Path(path)
        if path.is_dir():
            path = path / "style.toml"
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        meta = data.get("meta", {})
        # A style written before video types existed has no meta.type, and its
        # parent folder is the slug rather than the type.
        slug = meta.get("slug", path.parent.name)
        vt = types_mod.get_type(meta.get("type") or types_mod.DEFAULT_TYPE)
        return cls(
            name=meta.get("name", slug),
            slug=slug,
            type=vt.slug,
            description=meta.get("description", ""),
            created=meta.get("created", ""),
            source_song=meta.get("source_song", ""),
            params=vt.params_from(data),
        )

    # ---------- preview ----------

    def preview_video(self, root: str | Path = DEFAULT_ROOT) -> Path:
        return self.dir(root) / "preview.mp4"

    def preview_poster(self, root: str | Path = DEFAULT_ROOT) -> Path:
        return self.dir(root) / "preview.png"

    def has_preview(self, root: str | Path = DEFAULT_ROOT) -> bool:
        return self.preview_video(root).exists()

    def preview_url(self) -> str:
        return f"/styles/{self.type}/{self.slug}/preview.mp4"

    def to_dict(self, root: str | Path = DEFAULT_ROOT) -> dict:
        d = {
            "name": self.name,
            "slug": self.slug,
            "type": self.type,
            # The gallery groups by family, and a style with none defaulted to
            # "lyric" -- which put every beatsync look in the lyric row, under
            # a heading saying it needed words.
            "family": self.video_type.family,
            "description": self.description,
            "created": self.created,
            "source_song": self.source_song,
            "has_preview": self.has_preview(root),
            "preview": self.preview_url(),
        }
        d.update({s: asdict(getattr(self.params, s)) for s in self.sections})
        return d


# ------------------------------------------------------------------ registry

def _style_dirs(root: Path):
    """Every style folder under root, tolerating the pre-type flat layout."""
    if not root.exists():
        return
    for d in sorted(root.iterdir()):
        if not d.is_dir():
            continue
        if (d / "style.toml").exists():
            yield d                          # legacy: styles/<slug>/
            continue
        for sub in sorted(d.iterdir()):       # styles/<type>/<slug>/
            if sub.is_dir() and (sub / "style.toml").exists():
                yield sub


def list_styles(root: str | Path = DEFAULT_ROOT,
                type: str | None = None) -> list[Style]:
    out = []
    for d in _style_dirs(Path(root)):
        try:
            st = Style.load(d)
        except Exception:
            continue
        if type is None or st.type == type:
            out.append(st)
    return sorted(out, key=lambda s: (s.type, s.name))


class AmbiguousStyle(LookupError):
    """A bare slug names more than one style.

    Its own class because it is a caller's mistake rather than a missing file:
    the style is there, twice, and which one was meant has to be said.
    """


def get_style(slug: str, root: str | Path = DEFAULT_ROOT,
              type: str | None = None) -> Style:
    """One style, by slug and -- when it matters -- by renderer.

    A style's identity is `(type, slug)`: that is how it is filed on disk, and
    two renderers may honestly both have a "Tide". This used to return the
    FIRST match for a bare slug, which meant `get_style("tide")` was always
    swell's and `window/tide` could not be reached at all. Worse, `run` takes
    the resolved style's `type` as the renderer to use, so a bare slug could
    quietly change which renderer you got -- and `delete_style` removed the
    first match, which is the wrong directory.

    So an ambiguous bare slug is refused rather than guessed at.
    """
    found = [st for st in list_styles(root)
             if st.slug == slug and (type is None or st.type == type)]
    if not found:
        where = f" for {type}" if type else ""
        raise FileNotFoundError(f"no style {slug!r}{where} in {root}")
    if len(found) > 1:
        raise AmbiguousStyle(
            f"{slug!r} is a style of {', '.join(sorted(s.type for s in found))}; "
            f"say which renderer is meant")
    return found[0]


def delete_style(slug: str, root: str | Path = DEFAULT_ROOT,
                 type: str | None = None) -> None:
    """Remove a style, permanently.

    `type` is effectively required: this calls `shutil.rmtree`, and on a slug
    two renderers share it used to delete whichever sorted first. Deleting the
    wrong thing irrecoverably is not a defect to leave to chance, so an
    ambiguous slug raises rather than picking.
    """
    try:
        st = get_style(slug, root, type)
    except FileNotFoundError:
        return
    d = st.dir(root)
    if d.exists():
        shutil.rmtree(d)


# Neutral words used to render every style preview. Deliberately not any song's
# lyrics: a preview made from the loaded song could not be shared or committed,
# which is why previews used to be per-machine and remade constantly.
PREVIEW_CUES = Path(__file__).parent / "data" / "preview_cues.tsv"

# How bright the brightest pixel of a lyric preview must get, 0-1, before the
# capture counts as having shown a word. The bold layer draws white, so a lit
# word lands near 1.0 and a field with none tops out around 0.4.
BOLD_PEAK = 0.78


class StillPreview(RuntimeError):
    """A capture came back as the same frame repeated.

    Its own class because it is recoverable in a way a failed render is not:
    the style is fine, the moment was wrong, and the caller can try another.
    """


class WordlessPreview(StillPreview):
    """A lyric preview came back with no word ever lit.

    A subclass because it is recoverable the same way and every caller already
    retries `StillPreview` at the next moment. Worth its own name because the
    cause is different: the picture moved, it just had no lyrics in it, which is
    what a lyric style exists to show. Four shipped previews were in this state
    -- parked at the busiest drum window, minutes past the last placeholder cue
    -- and every check passed them, motion included.
    """


class FallbackPreview(RuntimeError):
    """The field script could not read the params it was just given.

    Not a `StillPreview`: retrying at another moment cannot help, because the
    picture is of the renderer's compiled-in defaults rather than of this look
    and would be identical at every moment. It is a wiring fault, and the
    callers that walk a list of moments should stop rather than walk it.
    """


PREVIEW_BOX = "_preview"


def _scratch_network(client, cfg, say):
    """Build this renderer's own network somewhere the song cannot be hurt.

    Previews used to be captured by pushing a style's params and field script
    into the live project and putting the song's own back afterwards. That
    worked for exactly as long as every renderer shared one network -- it was
    only ever swapping maths inside the same character grid.

    It cannot work now. Nine renderers have nine different sets of operators,
    so pushing `rings`' field script into a project wired for `lyric_grid`
    writes into operators that are not there. And building `rings` into
    `/project1` to fix that would destroy the network of whatever song happens
    to be open.

    So a preview builds into its own container and records from that. The song
    is never touched at all, which also retires the whole restore-on-failure
    path this function used to need.
    """
    from .sync import ROOT

    box = f"{ROOT}/{PREVIEW_BOX}"
    client.run(
        "def go():\n"
        f"    r = op({ROOT!r})\n"
        f"    e = r.op({PREVIEW_BOX!r})\n"
        "    if e: e.destroy()\n"
        f"    b = r.create(baseCOMP, {PREVIEW_BOX!r})\n"
        "    b.nodeX, b.nodeY = -2400, 1400\n"
        "go()")
    say(f"building the {cfg.type} network to preview in")
    cfg.video_type.build(client, cfg, progress=lambda m: None, container=box,
                         push=False)
    return box


def _drop_scratch(client) -> None:
    from .sync import ROOT
    try:
        client.run(
            "def go():\n"
            f"    e = op({ROOT + '/' + PREVIEW_BOX!r})\n"
            "    if e: e.destroy()\n"
            "go()")
    except Exception:
        pass


def capture_preview(client, style: Style, at: float = 1.0, seconds: float = 4.0,
                    root: str | Path = DEFAULT_ROOT, fps: int = 24,
                    width: int = 240, progress=None,
                    restore_cues: bool = True, live: Config | None = None) -> Path:
    """Render this style's preview, once.

    For a lyric style the words come from `data/preview_cues.tsv`, never from
    the song that happens to be loaded -- that is what makes a preview
    song-independent, and therefore storable and shareable rather than remade on
    every machine. A style whose type needs no lyrics is given none: pushing a
    cue table for a renderer that never reads one would only mean restoring it
    afterwards for nothing.

    Pass `live` -- the config the project is actually wearing -- to preview a
    style the project is *not* wearing. This function used to record whatever
    happened to be pushed, which quietly made it useless for any style but the
    one just applied: asked for five looks it would have produced five copies of
    the current one and reported success each time. With `live` it pushes the
    style's own params and its type's field script, and puts the song's back
    when it is done.

    Everything it changes in the live project is restored in `finally`, so an
    interrupted or failed capture does not leave the song wearing a preview.
    """
    from . import render as render_mod
    from . import sync
    from .cues import CueTable
    from .sync import OUT_TOP

    say = progress or (lambda m: None)
    wants_words = style.video_type.needs_lyrics

    # Asked before anything is recorded, because it is arithmetic and a capture
    # is minutes. `PREVIEW_CUES` stops at 7.5s; previews were being parked at
    # the busiest *drum* window, 56.6s into the benchmark song, so all five
    # lyric styles recorded a field 49 seconds past the last word. Every check
    # passed them -- the container parsed, the band was filled, the picture
    # moved, because the ambient field drifts whether or not a word is sung.
    if wants_words:
        from .cues import CueTable as _CT
        due = [c.start for c in _CT.load(PREVIEW_CUES).cues
               if at <= c.start < at + seconds]
        if not due:
            raise WordlessPreview(
                f"no placeholder word is sung in the {seconds:g}s from "
                f"{at:.1f}s, so a {style.name} preview taken there cannot show "
                f"one; the words run to "
                f"{max(c.start for c in _CT.load(PREVIEW_CUES).cues):.1f}s")
        say(f"{len(due)} placeholder words in the window")

    # The style's own look has to be in the project before anything is recorded,
    # and it has to come back out afterwards. The measured facts stay the song's
    # -- a beat renderer previewed against a neutral 120bpm fallback would be
    # showing its timing against nothing.
    import copy

    # The look to record, with the song's own measured facts under it: a beat
    # renderer previewed against a neutral 120bpm fallback would be showing its
    # timing against nothing.
    shown = style.apply_to(Config(type=style.type))
    if live is not None:
        shown.track = copy.deepcopy(live.track)

    box = _scratch_network(client, shown, say)
    try:
        say(f"pushing the {style.name} look")
        src = shown.video_type.field_source()
        if src:
            client.write(f"{box}/v7_script_callbacks", src)
        # Written the way `sync` writes it, not a second hand-rolled
        # encoding of the same dict: the two disagreed, and a field
        # script that cannot read its params does not fail -- it draws
        # its fallbacks and reports success.
        client.write(f"{box}/params", sync.params_text(shown))
        if wants_words:
            say("pushing the placeholder words")
            client.write(f"{box}/lyrics",
                         CueTable.load(PREVIEW_CUES).to_dat_text())
        # The drums the song actually has, so a beat renderer answers a real
        # rhythm rather than an empty table.
        if live is not None:
            try:
                from .drums import DrumTable
                from .workspace import Workspace
                ws = Workspace.open(getattr(live.track, "title", "") or "")
                if ws.drums_path.exists():
                    client.write(f"{box}/drums",
                                 DrumTable.load(ws.drums_path).to_dat_text())
            except Exception:
                pass                    # a preview without drums is still a preview

        d = style.dir(root)
        d.mkdir(parents=True, exist_ok=True)
        raw = d / "_raw.mp4"

        # Did the script make anything of what was just written? A capture
        # drawn from the defaults compiled into the field script is
        # indistinguishable from a capture of the style -- it moves, it lights
        # its words, it parses -- except that every style of that renderer
        # comes back as the same video. Seven did.
        if src:
            read = sync.params_were_read(client, box)
            if read is False:
                raise FallbackPreview(
                    f"the {shown.type} field script cannot read the params "
                    f"just pushed, so a {style.name} preview would be a "
                    f"recording of that renderer's defaults")

        # Through `park` rather than setting the frame here: a seek outside the
        # play range is discarded silently, and a style preview captured from
        # the wrong moment is indistinguishable from a style that looks wrong.
        say(f"cueing preview at {at:.2f}s")
        render_mod.park(client, at, covers=at + seconds + 2.0)
        say(f"recording {seconds:.0f}s")
        client.call("render", output=str(raw), duration=seconds + 1.5,
                    top=f"{box}/out", fps=fps)
        client.run("me.time.play = 1")

        if not render_mod.wait_for_container(raw, timeout=420.0):
            raise RuntimeError("preview capture did not produce a valid container")

        say("encoding preview")
        import subprocess
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
             "-t", f"{seconds:g}", "-an",
             "-vf", f"scale={width}:-2",
             "-c:v", "libx264", "-crf", "26", "-preset", "veryfast",
             "-movflags", "+faststart", "-pix_fmt", "yuv420p",
             str(style.preview_video(root))],
            check=True,
        )
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", f"{seconds / 2:g}", "-i", str(style.preview_video(root)),
             "-frames:v", "1", str(style.preview_poster(root))],
            check=True,
        )
        raw.unlink(missing_ok=True)

        # A preview exists to show motion. If it came back as one frame
        # repeated, it is not a calm style -- it is a broken capture, and every
        # other check passes it: the container parses, the brightness is in
        # range, the band is filled. Say so rather than shipping a still.
        moved = render_mod.measure_motion(style.preview_video(root),
                                          peak_width=width)
        say(f"{moved['frames']} frames, motion {moved['motion']}, "
            f"peak {moved['peak']}")
        if not moved["moving"]:
            raise StillPreview(
                f"the {style.name} preview is a still frame "
                f"(motion {moved['motion']} over {moved['frames']} frames); "
                f"nothing moved in the {seconds:g}s from {at:.1f}s")
        # Motion is not enough for a lyric style: the ambient field drifts on
        # its own, so a capture parked where the placeholder cues are not still
        # moves. The question is whether a word ever reached the bold layer.
        if wants_words and moved["peak"] < BOLD_PEAK:
            raise WordlessPreview(
                f"the {style.name} preview never lights a word "
                f"(peak {moved['peak']:.2f} of the bold layer's {BOLD_PEAK}); "
                f"the {seconds:g}s from {at:.1f}s hold no placeholder cues")
        # There is deliberately no brightness floor here. One was written and
        # then measured away: the seven broken backdrop previews came in at a
        # mean of 0.44-0.46 of 255, and the honest previews of Marquee and
        # Constellation -- styles whose whole idea is words out of near-black --
        # measure 0.11-0.15. The broken captures were BRIGHTER than the good
        # ones, so no floor can tell them apart, and the one tried here refused
        # three styles that were working. What distinguishes a broken capture is
        # not how dark it is but that it is a recording of the renderer's
        # defaults, which is what `FallbackPreview` above asks directly.
    finally:
        # Nothing to put back. The song's network, words and look were never
        # touched -- the whole capture happened inside its own container --
        # which retires a restore path that had to be right on every failure
        # and interruption, and once left a song wearing "lorem ipsum".
        _drop_scratch(client)
    style.stamp_preview(root)
    say("preview ready")
    return style.preview_video(root)
