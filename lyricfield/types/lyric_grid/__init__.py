"""Lyric grid: the song's own words as a dense character field.

Words sit dim and drifting, brighten in place on cue, and answer the beat as
light -- a kick opens a radial ripple, a snare scatters sparks, and before the
kick enters the field twinkles on the tempo grid. Nothing scales and no glyph
swaps; the beat is expressed only as brightness.

Needs lyrics: the cue table is the whole subject.
"""

from __future__ import annotations

from .. import CUES, INSTRUMENTAL, LYRIC, VideoType
from .build import build as _build, verify as _verify
from .params import (Analysis, Beat, Cueing, Grid, Look, LyricGrid, LyricLook,
                     Params)

TYPE = VideoType(
    slug="lyric_grid",
    name="Lyric grid",
    description="the song's words as a dense character field, lit on cue",
    params_cls=Params,
    family=LYRIC,
    # A clean instrumental, because vocals pollute onset detection, and the cue
    # table, because the words are the whole subject.
    needs=frozenset({INSTRUMENTAL, CUES}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Grid", "Look", "LyricGrid", "LyricLook",
           "Cueing", "Beat", "Analysis"]
