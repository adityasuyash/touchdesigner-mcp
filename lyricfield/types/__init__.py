"""Video types: the distinct visual systems a song can be rendered as.

Ingest is shared -- every type consumes the same substrate that `pipeline.prepare`
produces (stems, duration, kick entry, hi-hat entry, beat grid, silence windows,
and word-level cues). What differs is the renderer: its TouchDesigner network,
its tunables, and whether it needs lyrics at all.

A type is a package under this one exposing `TYPE`:

    lyricfield/types/<slug>/
        __init__.py   TYPE = VideoType(...)
        params.py     the tunables, as a sectioned dataclass with validate()
        field.py      optional: code that runs inside TouchDesigner
        build.py      optional: constructs the network from an empty project

`build` is what keeps the repo the source of truth. A type that cannot build
itself falls back to forking whatever TouchDesigner currently has open, which is
how the first type was made before this package existed -- workable for one type,
not for several.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).parent


# What a type can ask ingest for. Anything not asked for is never produced --
# a beatsync video on an instrumental track should not pay for a Demucs vocal
# split and a Groq transcription it will never read.
MIX, INSTRUMENTAL, VOCALS, CUES = "mix", "instrumental", "vocals", "cues"

LYRIC, BEATSYNC = "lyric", "beatsync"


@dataclass(frozen=True)
class VideoType:
    slug: str
    name: str
    description: str
    params_cls: type
    # Which kind of video this makes. Lyric types draw the song's words and
    # cannot work without them; beatsync types need no vocals at all, which is
    # what lets the system serve instrumental tracks.
    family: str = LYRIC
    needs: frozenset = frozenset({INSTRUMENTAL, CUES})
    field_file: str = ""                      # filename inside the type package
    build: Callable[..., Any] | None = None   # build(client, cfg, progress=None)
    verify: Callable[..., Any] | None = None  # verify(client, cfg) -> [str]

    # ---------- params ----------

    def default_params(self):
        return self.params_cls()

    def params_from(self, data: dict):
        from ..sections import build_sections
        return build_sections(self.params_cls, data)

    def ranges(self) -> dict:
        """Slider bounds per tunable, declared alongside the params themselves."""
        mod = self._params_module()
        return {k: list(v) for k, v in getattr(mod, "RANGES", {}).items()} if mod else {}

    def _params_module(self):
        import importlib
        try:
            return importlib.import_module(f"{__name__}.{self.slug}.params")
        except Exception:
            return None

    def controls(self, params) -> list[dict]:
        """Named, grouped controls for this type, or [] if it declares none.

        A type is free to expose only raw tunables; the UI falls back to those.
        But a wall of internal variable names is not a set of choices, so a type
        that means to be used by a person should say what its knobs *do*.
        """
        mod = self._params_module()
        fn = getattr(mod, "controls_payload", None) if mod else None
        return fn(params) if fn else []

    def apply_control(self, params, key: str, value: float) -> dict:
        mod = self._params_module()
        fn = getattr(mod, "apply_control", None) if mod else None
        if not fn:
            raise KeyError(f"{self.slug} declares no controls")
        return fn(params, key, value)

    def section_names(self) -> tuple[str, ...]:
        from ..sections import section_names
        return section_names(self.params_cls)

    # ---------- touchdesigner ----------

    @property
    def field_path(self) -> Path | None:
        if not self.field_file:
            return None
        return HERE / self.slug / self.field_file

    def field_source(self) -> str | None:
        """The code that runs inside TouchDesigner, prelude included.

        A field script is pushed as a single DAT and cannot import a sibling, so
        anything every renderer needs has to travel with it. Concatenating
        `_prelude.py` is how three copies of the same drum lookup are avoided --
        the ring maths was already duplicated between two of them before this
        existed.
        """
        p = self.field_path
        if not (p and p.exists()):
            return None
        body = p.read_text(encoding="utf-8")
        prelude = Path(__file__).parent / "_prelude.py"
        if prelude.exists():
            return prelude.read_text(encoding="utf-8") + "\n\n" + body
        return body

    def regions(self, cfg) -> dict:
        """Crops a rendered still should be measured over, as (x, y, w, h).

        A type that does not care returns nothing and the whole frame is used.
        Keeping this on the type is what stops shared code from reaching into
        one renderer's vocabulary -- `do_stills` used to read `cfg.grid.band`
        directly, which raised for any other type.
        """
        fn = getattr(cfg.params, "regions", None)
        return dict(fn()) if callable(fn) else {}

    @property
    def can_build(self) -> bool:
        return self.build is not None and self.verify is not None

    @property
    def needs_lyrics(self) -> bool:
        """Derived, not declared: a type needs lyrics exactly when it asks for
        cues. Keeping it as a separate flag let the two disagree."""
        return CUES in self.needs

    @property
    def needs_separation(self) -> bool:
        return bool(self.needs & {INSTRUMENTAL, VOCALS})

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "family": self.family,
            "needs": sorted(self.needs),
            "needs_lyrics": self.needs_lyrics,
            "can_build": self.can_build,
            "sections": list(self.section_names()),
            "ranges": self.ranges(),
        }


# ------------------------------------------------------------------ registry

_CACHE: dict[str, VideoType] = {}


def _discover() -> dict[str, VideoType]:
    if _CACHE:
        return _CACHE
    for info in pkgutil.iter_modules([str(HERE)]):
        if not info.ispkg:
            continue
        try:
            mod = importlib.import_module(f"{__name__}.{info.name}")
        except Exception:
            continue
        t = getattr(mod, "TYPE", None)
        if isinstance(t, VideoType):
            _CACHE[t.slug] = t
    return _CACHE


def list_types() -> list[VideoType]:
    return sorted(_discover().values(), key=lambda t: t.name)


def get_type(slug: str) -> VideoType:
    types = _discover()
    if slug not in types:
        known = ", ".join(sorted(types)) or "none"
        raise KeyError(f"no video type {slug!r} (known: {known})")
    return types[slug]


DEFAULT_TYPE = "lyric_grid"
