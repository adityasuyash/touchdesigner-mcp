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
        return Path(root) / self.type / self.slug

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


def get_style(slug: str, root: str | Path = DEFAULT_ROOT,
              type: str | None = None) -> Style:
    for st in list_styles(root):
        if st.slug == slug and (type is None or st.type == type):
            return st
    raise FileNotFoundError(f"no style {slug!r} in {root}")


def delete_style(slug: str, root: str | Path = DEFAULT_ROOT,
                 type: str | None = None) -> None:
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


class StillPreview(RuntimeError):
    """A capture came back as the same frame repeated.

    Its own class because it is recoverable in a way a failed render is not:
    the style is fine, the moment was wrong, and the caller can try another.
    """


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

    before = None
    if restore_cues and wants_words:
        try:
            before = sync.pull_cues(client)
        except Exception:
            before = None

    # The style's own look has to be in the project before anything is recorded,
    # and it has to come back out afterwards. The measured facts stay the song's
    # -- a beat renderer previewed against a neutral 120bpm fallback would be
    # showing its timing against nothing.
    restore_cfg = None
    if live is not None:
        import copy
        restore_cfg = copy.deepcopy(live)
        shown = style.apply_to(Config(type=style.type))
        shown.track = copy.deepcopy(live.track)
        say(f"pushing the {style.name} look")
        sync.push_field(client, shown)
        sync.push_params(client, shown)
        sync.reset_field_state(client)

    # Anything pushed into the live project has to come back even when the
    # render fails or is interrupted -- otherwise the next preview of the *song*
    # silently shows "lorem ipsum", or another style's look.
    try:
        if wants_words:
            say("pushing the placeholder words")
            sync.push_cues(client, CueTable.load(PREVIEW_CUES))
            sync.reset_field_state(client)
        d = style.dir(root)
        d.mkdir(parents=True, exist_ok=True)
        raw = d / "_raw.mp4"

        # Through `park` rather than setting the frame here: a seek outside the
        # play range is discarded silently, and a style preview captured from
        # the wrong moment is indistinguishable from a style that looks wrong.
        say(f"cueing preview at {at:.2f}s")
        render_mod.park(client, at, covers=at + seconds + 2.0)
        say(f"recording {seconds:.0f}s")
        client.call("render", output=str(raw), duration=seconds + 1.5,
                    top=OUT_TOP, fps=fps)
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
        moved = render_mod.measure_motion(style.preview_video(root))
        say(f"{moved['frames']} frames, motion {moved['motion']}")
        if not moved["moving"]:
            raise StillPreview(
                f"the {style.name} preview is a still frame "
                f"(motion {moved['motion']} over {moved['frames']} frames); "
                f"nothing moved in the {seconds:g}s from {at:.1f}s")
    finally:
        if before is not None and before.cues:
            say("restoring the song's own words")
            try:
                sync.push_cues(client, before)
                sync.reset_field_state(client)
            except Exception as e:
                say(f"could not restore the cue table: {e}")
        if restore_cfg is not None:
            say("restoring the song's own look")
            try:
                sync.push_field(client, restore_cfg)
                sync.push_params(client, restore_cfg)
                sync.reset_field_state(client)
            except Exception as e:
                say(f"could not restore the song's settings: {e}")
    say("preview ready")
    return style.preview_video(root)
