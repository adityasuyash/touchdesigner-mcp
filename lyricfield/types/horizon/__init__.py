"""Horizon: a neon grid running to a banded sun, with the lyrics standing in it.

The only renderer here that draws a *place*. Everything else is a pattern over
black -- glyphs, rings, bands, type. This has a floor in real perspective, a
horizon, and a sliced sun sitting on it, in two colliding hues, and the words
stand in the scene rather than floating in front of nothing.

The floor is genuine perspective rather than a skewed grid: depth is
`1 / (horizon - y)`, which is what a plane under a camera gives, so the lanes
converge and the rungs bunch toward the horizon exactly as they should.
"""

from __future__ import annotations

from .. import CUES, DRUMS, INSTRUMENTAL, LYRIC, VideoType
from .build import build as _build, verify as _verify
from .params import Beat, Frame, Ground, Line, Look, Params, Sun

TYPE = VideoType(
    slug="horizon",
    name="Horizon",
    description="a neon grid running to a banded sun, with the words in it",
    params_cls=Params,
    family=LYRIC,
    needs=frozenset({INSTRUMENTAL, CUES, DRUMS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Frame", "Ground", "Sun", "Line", "Look", "Beat"]
