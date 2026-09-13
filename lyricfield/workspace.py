"""One self-contained folder per song.

    <root>/<song-slug>/
        project.toe        this song's TouchDesigner project
        config.toml        this song's tunables + measured track facts
        cues.tsv           this song's cue table
        source/            the original audio
        stems/             vocals.wav, no_vocals.wav
        exports/           renders, and exports/stills/

Everything a song needs travels together, so a finished piece can be archived or
handed over as a single directory.

On creating the project file: rather than keeping a template .toe in the repo
(binary, undiffable, and immediately stale), a new song's project is forked from
whatever TouchDesigner currently has open, via `project.save(<new path>)`. The
live project is the template. `sync.push_all` then loads this song's script,
params and cues into it.

The constraint to remember is that TouchDesigner holds exactly one project open,
and the MCP server lives *inside* that project. Switching songs means opening a
different .toe by hand; the connection drops with the old one and returns with
the new. `Workspace.is_open_in` checks which project TD actually has loaded, so
a push can refuse to write a song's data into the wrong project.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .cues import CueTable
from .styles import Style, get_style

DEFAULT_ROOT = Path.home() / "lyricfield-projects"

_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    s = _SLUG.sub("-", name.strip().lower()).strip("-")
    return s or "untitled"


@dataclass
class Workspace:
    root: Path
    slug: str
    name: str = ""

    # ---------- paths ----------

    @property
    def dir(self) -> Path:
        return self.root / self.slug

    @property
    def project(self) -> Path:
        return self.dir / "project.toe"

    @property
    def current_project(self) -> Path:
        """The newest project*.toe in this folder.

        TouchDesigner increments the version on every save, so the file being
        written is project.toe, then project.1.toe, then project.2.toe. The
        highest number is the live one; the rest are free backups. Use this
        whenever you mean "this song's project as it stands now".
        """
        def version(path: Path) -> int:
            parts = path.name.split(".")
            return int(parts[1]) if len(parts) == 3 and parts[1].isdigit() else 0

        takes = sorted(self.dir.glob("project*.toe"), key=version)
        return takes[-1] if takes else self.project

    @property
    def config_path(self) -> Path:
        return self.dir / "config.toml"

    @property
    def cues_path(self) -> Path:
        return self.dir / "cues.tsv"

    @property
    def source_dir(self) -> Path:
        return self.dir / "source"

    @property
    def stems_dir(self) -> Path:
        return self.dir / "stems"

    @property
    def exports_dir(self) -> Path:
        return self.dir / "exports"

    @property
    def stills_dir(self) -> Path:
        return self.exports_dir / "stills"

    def export_path(self, suffix: str = "", ext: str = "mp4") -> Path:
        """Next free export name: <slug>.mp4, <slug>_002.mp4, ... so a re-render
        never silently overwrites the take you were comparing against."""
        self.exports_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{self.slug}{('_' + suffix) if suffix else ''}"
        candidate = self.exports_dir / f"{stem}.{ext}"
        n = 2
        while candidate.exists():
            candidate = self.exports_dir / f"{stem}_{n:03d}.{ext}"
            n += 1
        return candidate

    # ---------- lifecycle ----------

    @classmethod
    def create(cls, name: str, source_audio: str | Path | None = None,
               root: str | Path = DEFAULT_ROOT,
               style: str | Style | None = None,
               copy_source: bool = True) -> "Workspace":
        ws = cls(root=Path(root).expanduser(), slug=slugify(name), name=name)
        for d in (ws.dir, ws.source_dir, ws.stems_dir, ws.exports_dir, ws.stills_dir):
            d.mkdir(parents=True, exist_ok=True)

        cfg = Config()
        if style is not None:
            st = style if isinstance(style, Style) else get_style(style)
            cfg = st.apply_to(cfg)

        if source_audio:
            src = Path(source_audio).expanduser()
            if copy_source and src.exists():
                dst = ws.source_dir / src.name
                if not dst.exists():
                    shutil.copy2(src, dst)
                src = dst
            cfg.track.source = str(src)

        if not ws.config_path.exists():
            cfg.save(ws.config_path)
        if not ws.cues_path.exists():
            CueTable().save(ws.cues_path)
        return ws

    @classmethod
    def open(cls, slug: str, root: str | Path = DEFAULT_ROOT) -> "Workspace":
        ws = cls(root=Path(root).expanduser(), slug=slug, name=slug)
        if not ws.dir.exists():
            raise FileNotFoundError(f"no workspace {slug!r} under {ws.root}")
        cfg = Config.load(ws.config_path)
        ws.name = cfg.track.title or slug
        return ws

    # ---------- state ----------

    def load_config(self) -> Config:
        return Config.load(self.config_path)

    def save_config(self, cfg: Config) -> None:
        cfg.save(self.config_path)

    def load_cues(self) -> CueTable:
        return CueTable.load(self.cues_path)

    def save_cues(self, table: CueTable) -> None:
        table.save(self.cues_path)

    def apply_style(self, style: str | Style) -> Config:
        st = style if isinstance(style, Style) else get_style(style)
        cfg = st.apply_to(self.load_config())
        cfg.track.style = st.slug
        self.save_config(cfg)
        return cfg

    # ---------- touchdesigner ----------

    def fork_project_from_current(self, client, timeout: float = 420.0) -> Path:
        """Save whatever TD currently has open into this workspace as project.toe.

        This is how a new song gets its project: the live network becomes the
        template. TD keeps working on the *new* file afterwards, which is what
        you want -- you are now editing this song.
        """
        from . import sync
        sync.quiesce(client)
        target = str(self.project)
        try:
            client.run(
                f"project.save({target!r})\nprint(project.name)",
                timeout=timeout,
            )
        except Exception:
            # TD routinely stops answering mid-save and finishes anyway
            if not client.wait_until_ready(seconds=timeout):
                raise
        if not self.project.exists():
            raise RuntimeError(
                f"TD reported saving but {self.project} does not exist. "
                "Check the path is writable."
            )
        # TD increments on save: it wrote project.toe and its live project is
        # now project.1.toe. Hand back the one it will keep writing to.
        live = self.live_project_in(client)
        if live is not None and live.parent.resolve() == self.dir.resolve():
            return live
        return self.project

    def live_project_in(self, client) -> Path | None:
        """The .toe TouchDesigner actually has open, or None if it cannot say."""
        try:
            out = client.run(
                "def main():\n"
                "    import os\n"
                "    return os.path.join(project.folder, project.name)\n"
                "print(main())"
            ).strip()
        except Exception:
            return None
        return Path(out) if out else None

    def is_open_in(self, client) -> bool:
        """Is TD actually running this workspace's project?

        Matches on the folder, not the exact filename. TouchDesigner increments
        the version on every save -- ask it to write project.toe and its live
        project becomes project.1.toe, then project.2.toe -- so an exact-name
        comparison reports "wrong project" forever and the guard that should
        stop a push landing in the wrong song refuses every push instead.
        Any project*.toe inside this workspace is this song.
        """
        live = self.live_project_in(client)
        if live is None:
            return False
        try:
            return (live.parent.resolve() == self.dir.resolve()
                    and live.name.startswith("project") and live.suffix == ".toe")
        except OSError:
            return False

    def to_dict(self) -> dict:
        cfg = self.load_config() if self.config_path.exists() else Config()
        cues = self.load_cues() if self.cues_path.exists() else CueTable()
        exports = sorted(p.name for p in self.exports_dir.glob("*.mp4")) \
            if self.exports_dir.exists() else []
        return {
            "slug": self.slug,
            "name": self.name,
            "dir": str(self.dir),
            "has_project": self.project.exists(),
            "cues": len(cues.cues),
            "lines": len(cues.lines),
            "duration": cfg.track.duration,
            "style": getattr(cfg.track, "style", ""),
            "exports": exports,
        }


def list_workspaces(root: str | Path = DEFAULT_ROOT) -> list[Workspace]:
    root = Path(root).expanduser()
    if not root.exists():
        return []
    out = []
    for d in sorted(root.iterdir()):
        if (d / "config.toml").exists():
            out.append(Workspace(root=root, slug=d.name, name=d.name))
    return out
