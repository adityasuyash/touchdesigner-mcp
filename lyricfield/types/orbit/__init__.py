"""Orbit: the line rides a curve, a character at a time.

The renderer that proves the lattice is gone. Every other lyric type here --
the three grid ones included -- places glyphs where something structural put
them: a cell, a centred line, a wrapped block. No parameter escapes that,
because the structure *is* the renderer.

This one gives each character its own coordinate on a parametric curve, through
the Text TOP's Specification DAT, so the type can be anywhere at all. Circle,
spiral, travelling wave or a figure that crosses itself; the whole thing turns,
and a kick breathes it outward.
"""

from __future__ import annotations

from .. import CUES, DRUMS, INSTRUMENTAL, LYRIC, VideoType
from .build import build as _build, verify as _verify
from .params import PATHS, Beat, Frame, Line, Look, Params, Path

TYPE = VideoType(
    slug="orbit",
    name="Orbit",
    description="the lyrics riding a curve, a character at a time",
    params_cls=Params,
    family=LYRIC,
    needs=frozenset({INSTRUMENTAL, CUES, DRUMS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Frame", "Path", "Line", "Look", "Beat", "PATHS"]
