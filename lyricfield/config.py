"""A song's configuration: what track it is, which video type, and that type's tunables.

    [video]   which renderer this song uses
    [track]   per-song facts -- paths, and the values lyricfield.analysis measured
    ...       one section per tunable group, owned by the video type

Splitting it this way is what lets a type be swapped without touching song data,
and what lets a style (a named preset of the type's tunables) be provably unable
to overwrite the track. The type owns its sections and the constraints between
them; see `lyricfield/types/<slug>/params.py`.

Older config files that predate video types have no `[video]` section. They load
as `lyric_grid`, whose sections are exactly the `grid`/`look`/`cueing`/`beat` the
old format used, so nothing needs migrating.
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from . import types as types_mod
from .sections import build_sections, flatten, sections_toml, toml_value


@dataclass
class Track:
    """Per-song facts. Paths and identity are set when the workspace is created;
    the measured values are filled in by lyricfield.analysis."""
    title: str = ""
    source: str = ""            # the original audio file
    style: str = ""             # slug of the style last applied
    # Which beat preset was picked, stored beside `style` so a reload shows it.
    # Named `back_style` from when the beat was a renderer composited BEHIND the
    # words; it is an effect on them now. `back_type` -- that renderer's slug --
    # went with the family, and its one surviving reader was
    # `Workspace.provision`, asking `cfg.back_type` where the field lives on
    # `Track`. Nothing wrote it, so it was never anything but an AttributeError,
    # and it raised on every provision of every renderer.
    back_style: str = ""
    vocals: str = ""
    instrumental: str = ""
    # The isolated drums, when separation produced one. What the beat is
    # measured from; a song separated before four-stem mode has none and falls
    # back to the mix, which measures better than the instrumental does.
    drums: str = ""
    duration: float = 0.0
    kick_in: float = 0.0
    beat_anchor: float = 0.0
    beat_period: float = 0.4615
    high_in: float = 0.0
    # Where singing actually starts, from the vocal stem rather than the cue
    # table -- transcription can drop a quiet opening line, and on one song it
    # reported 11 seconds of singing with no words cued against it. Measured
    # already; it just had nowhere to live, so the UI could not offer it.
    vocal_in: float = 0.0
    # How loud this master is (90th-percentile frame RMS), so the absolute gates
    # TouchDesigner applies can be scaled to it rather than to whichever track
    # they were originally tuned on.
    level: float = 0.0
    hold_windows: list[list[float]] = field(default_factory=list)


@dataclass
class Config:
    type: str = types_mod.DEFAULT_TYPE
    track: Track = field(default_factory=Track)
    params: Any = None
    # What the beat does to the words: an effect on this layer, not a second
    # renderer behind it. Seven renderers were built on the other premise
    # before it turned out to be the wrong one; see `beat.py`.
    # Called `response` rather than `beat` because every renderer already has a
    # `[beat]` section of its own -- what the drums do INSIDE its picture -- and
    # `Config` flattens sections into one namespace. Two things named `beat`
    # would silently keep whichever came last, which is the trap the meta-tests
    # exist for.
    response: Any = None
    beat_preset: str = "none"

    def __post_init__(self) -> None:
        if self.params is None:
            self.params = self.video_type.default_params()
        if self.response is None:
            from .beat import preset
            self.response = preset(self.beat_preset or "none")

    # ---------- the beat ----------

    def with_beat(self, slug: str | None) -> "Config":
        """Wear a named beat preset, or none."""
        from .beat import preset
        slug = slug or "none"
        self.response = preset(slug)
        self.beat_preset = slug
        return self

    # ---------- type ----------

    @property
    def video_type(self):
        return types_mod.get_type(self.type)

    def with_type(self, slug: str) -> "Config":
        """Switch renderer, keeping the song. The new type's tunables start at
        its defaults -- they describe a different renderer and do not carry over."""
        t = types_mod.get_type(slug)
        return Config(type=slug, track=self.track, params=t.default_params())

    # ---------- section access ----------

    def __getattr__(self, name: str):
        # `cfg.grid`, `cfg.look`, ... read through to the active type's params.
        # Only reached for attributes the dataclass itself does not define.
        params = self.__dict__.get("params")
        if params is not None and hasattr(params, name):
            return getattr(params, name)
        raise AttributeError(
            f"{type(self).__name__!r} has no attribute {name!r} "
            f"(type {self.__dict__.get('type')!r} has sections "
            f"{list(self.__dict__.get('params').__dataclass_fields__) if params else []})"
        )

    def sections(self) -> dict[str, Any]:
        """Every section as plain dicts, including track -- what the UI renders."""
        out = {"track": asdict(self.track)}
        for f in fields(self.params):
            out[f.name] = asdict(getattr(self.params, f.name))
        return out

    # ---------- io ----------

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        path = Path(path)
        if not path.exists():
            return cls()
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        slug = (data.get("video") or {}).get("type") or types_mod.DEFAULT_TYPE
        try:
            vt = types_mod.get_type(slug)
        except KeyError:
            vt = types_mod.get_type(types_mod.DEFAULT_TYPE)
            slug = vt.slug
        track = build_sections(_TrackHolder, {"track": data.get("track", {})}).track

        # What the beat does to the words. `[beat]` names the preset and the
        # sections under it carry any hand-edit, so a tweaked preset survives a
        # reload rather than snapping back to the shipped numbers.
        from .beat import Response, preset, reconcile
        from .sections import build_sections as _bs

        blk = data.get("response") or {}
        name = blk.get("preset") or "none"
        try:
            resp = preset(name)
        except KeyError:
            name, resp = "none", preset("none")
        edits = {k: v for k, v in blk.items() if isinstance(v, dict)}
        if edits:
            resp = _bs(Response, edits)
            reconcile(resp)
        return cls(type=slug, track=track, params=vt.params_from(data),
                   response=resp, beat_preset=name)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_toml(), encoding="utf-8")

    def to_toml(self) -> str:
        out = [
            "# lyricfield configuration.",
            "# Regenerated by the UI; safe to hand-edit. The [video] type decides",
            "# which sections follow and what they mean -- see",
            f"# lyricfield/types/{self.type}/params.py for the constraints between them.",
            "",
            "[video]",
            f"type = {toml_value(self.type)}",
            "",
            "[track]",
        ]
        for k, v in asdict(self.track).items():
            out.append(f"{k} = {toml_value(v)}")
        out.append("")
        out.append(sections_toml(self.params))
        out += [
            "",
            "# What the beat does to the words. The preset names it; the",
            "# sections below are the numbers, so a hand-edit survives a reload.",
            "[response]",
            f"preset = {toml_value(self.beat_preset)}",
            "",
        ]
        body = sections_toml(self.response)
        # `[zoom]` -> `[response.zoom]`, so a section name means one thing.
        out.append("\n".join(
            f"[response.{ln[1:]}" if ln.startswith("[") else ln
            for ln in body.splitlines()))
        return "\n".join(out)

    def as_params(self) -> dict:
        """Flat dict injected into TouchDesigner alongside the field script."""
        p = flatten(self.params)
        p.update(asdict(self.track))
        p["hold_windows"] = [tuple(w) for w in self.track.hold_windows]
        return p

    # ---------- constraints ----------

    def validate(self) -> list[str]:
        return (self.track_problems() + list(self.params.validate())
                + list(self.response.validate()))

    def track_problems(self) -> list[str]:
        """What is wrong with the measured facts, as opposed to the tunables.

        Nothing checked these at all, and two of them reach TouchDesigner as
        divisors in a Script TOP that cooks every frame. A `beat_period` of zero
        is an OverflowError sixty times a second in the one place nothing is
        watching; a `duration` of zero sends the renderer to a fallback length
        that has nothing to do with the song.

        Only checked once measured: a fresh config legitimately has zeros in it,
        and complaining before ingest has run would be noise.
        """
        t, out = self.track, []
        measured = bool(t.duration or t.beat_period != Track.beat_period
                        or t.vocals or t.instrumental)
        if not measured:
            return out

        if t.duration <= 0:
            out.append("track duration is not measured; the renderer cannot "
                       "know how long the song is")
        if t.beat_period <= 0:
            out.append("beat_period must be positive -- it is a divisor "
                       "evaluated every frame inside TouchDesigner")
        for name in ("kick_in", "high_in", "beat_anchor"):
            v = getattr(t, name)
            if v < 0:
                out.append(f"{name} is negative ({v})")
            elif t.duration and v > t.duration:
                out.append(f"{name} ({v:.1f}s) is past the end of the "
                           f"{t.duration:.1f}s track")
        for name in ("vocals", "instrumental", "drums", "source"):
            path = getattr(t, name)
            if path and not Path(path).exists():
                out.append(f"{name} file is recorded but missing: {path}")
        for w in t.hold_windows:
            if len(w) != 2 or w[0] > w[1]:
                out.append(f"hold window {w} is not an ordered (start, end) pair")
                break
        return out


@dataclass
class _TrackHolder:
    """Lets `build_sections` fill a Track the same way it fills type sections."""
    track: Track = field(default_factory=Track)
