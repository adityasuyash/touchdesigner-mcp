"""Named, reusable animation styles.

A style is everything that decides how the field *looks and moves* — grid, look,
cueing, beat — with none of the per-song facts. That split already exists in
`Config`: `track` holds the song, the other four sections hold the style. So a
style is a Config with `track` removed, and applying one is a section-wise copy.

Each style keeps a short video loop as its preview. A still is not enough: drift
speed, dissolve, ripple and twinkle are all motion, and two styles can look
identical frozen while behaving completely differently.

Styles are tracked in the repo — they are the reusable output of the work, and
they contain no song data.
"""

from __future__ import annotations

import re
import shutil
import tomllib
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path

from .config import Beat, Config, Cueing, Grid, Look, _toml_value

STYLE_SECTIONS = ("grid", "look", "cueing", "beat")
DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "styles"

_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    s = _SLUG.sub("-", name.strip().lower()).strip("-")
    return s or "untitled"


@dataclass
class Style:
    name: str = "Untitled"
    slug: str = "untitled"
    description: str = ""
    created: str = ""
    source_song: str = ""
    grid: Grid = field(default_factory=Grid)
    look: Look = field(default_factory=Look)
    cueing: Cueing = field(default_factory=Cueing)
    beat: Beat = field(default_factory=Beat)

    # ---------- conversion ----------

    @classmethod
    def from_config(cls, cfg: Config, name: str, description: str = "",
                    source_song: str = "") -> "Style":
        import copy
        return cls(
            name=name,
            slug=slugify(name),
            description=description,
            created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source_song=source_song,
            grid=copy.deepcopy(cfg.grid),
            look=copy.deepcopy(cfg.look),
            cueing=copy.deepcopy(cfg.cueing),
            beat=copy.deepcopy(cfg.beat),
        )

    def apply_to(self, cfg: Config) -> Config:
        """Copy the style's sections onto a config, leaving `track` untouched."""
        import copy
        cfg.grid = copy.deepcopy(self.grid)
        cfg.look = copy.deepcopy(self.look)
        cfg.cueing = copy.deepcopy(self.cueing)
        cfg.beat = copy.deepcopy(self.beat)
        return cfg

    def as_config(self) -> Config:
        """A Config carrying this style and default (empty) track data."""
        return self.apply_to(Config())

    # ---------- io ----------

    def dir(self, root: str | Path = DEFAULT_ROOT) -> Path:
        return Path(root) / self.slug

    def save(self, root: str | Path = DEFAULT_ROOT) -> Path:
        d = self.dir(root)
        d.mkdir(parents=True, exist_ok=True)
        out = [
            "# lyricfield style. Reusable across songs; contains no song data.",
            "",
            "[meta]",
            f"name = {_toml_value(self.name)}",
            f"slug = {_toml_value(self.slug)}",
            f"description = {_toml_value(self.description)}",
            f"created = {_toml_value(self.created)}",
            f"source_song = {_toml_value(self.source_song)}",
            "",
        ]
        for section in STYLE_SECTIONS:
            out.append(f"[{section}]")
            for k, v in asdict(getattr(self, section)).items():
                out.append(f"{k} = {_toml_value(v)}")
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
        kw: dict = {
            "name": meta.get("name", path.parent.name),
            "slug": meta.get("slug", path.parent.name),
            "description": meta.get("description", ""),
            "created": meta.get("created", ""),
            "source_song": meta.get("source_song", ""),
        }
        for f in fields(cls):
            if f.name not in STYLE_SECTIONS:
                continue
            section = f.default_factory()          # type: ignore[misc]
            for k, v in data.get(f.name, {}).items():
                if hasattr(section, k):
                    setattr(section, k, v)
            kw[f.name] = section
        return cls(**kw)

    # ---------- preview ----------

    def preview_video(self, root: str | Path = DEFAULT_ROOT) -> Path:
        return self.dir(root) / "preview.mp4"

    def preview_poster(self, root: str | Path = DEFAULT_ROOT) -> Path:
        return self.dir(root) / "preview.png"

    def has_preview(self, root: str | Path = DEFAULT_ROOT) -> bool:
        return self.preview_video(root).exists()

    def to_dict(self, root: str | Path = DEFAULT_ROOT) -> dict:
        d = {
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "created": self.created,
            "source_song": self.source_song,
            "has_preview": self.has_preview(root),
        }
        d.update({s: asdict(getattr(self, s)) for s in STYLE_SECTIONS})
        return d


# ------------------------------------------------------------------ registry

def list_styles(root: str | Path = DEFAULT_ROOT) -> list[Style]:
    root = Path(root)
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if (d / "style.toml").exists():
            try:
                out.append(Style.load(d))
            except Exception:
                continue
    return out


def get_style(slug: str, root: str | Path = DEFAULT_ROOT) -> Style:
    d = Path(root) / slug
    if not (d / "style.toml").exists():
        raise FileNotFoundError(f"no style {slug!r} in {root}")
    return Style.load(d)


def delete_style(slug: str, root: str | Path = DEFAULT_ROOT) -> None:
    d = Path(root) / slug
    if d.exists():
        shutil.rmtree(d)


def capture_preview(client, style: Style, at: float, seconds: float = 4.0,
                    root: str | Path = DEFAULT_ROOT, fps: int = 24,
                    width: int = 360, progress=None) -> Path:
    """Render a short silent loop of the current TD state as this style's preview.

    `at` should be a moment with visible activity -- a cue firing, ideally over a
    busy stretch -- or the preview shows an idle field and tells you nothing.
    """
    from . import render as render_mod
    from .sync import OUT_TOP

    say = progress or (lambda m: None)
    d = style.dir(root)
    d.mkdir(parents=True, exist_ok=True)
    raw = d / "_raw.mp4"

    say(f"cueing preview at {at:.2f}s")
    client.run(
        "def main():\n"
        "    me.time.play = 0\n"
        f"    op('/local/time').frame = max(1, int({at!r} * 60))\n"
        "    return op('/local/time').frame\n"
        "print(main())"
    )
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
    say("preview ready")
    return style.preview_video(root)
