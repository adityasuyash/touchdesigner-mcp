"""Approach: the words travel toward you.

Taken from the Chainsmokers' "Closer" lyric video, where the lyrics fly through
three-dimensional space. It is the first renderer here that moves words in Z at
all -- `orbit` puts them on a curve, `swarm` throws them about the plane, but
both stay at one size in one flat frame.

Perspective is quantised into slabs because a Text TOP has one font size for its
whole Specification DAT; see `build.py`. Needs lyrics.
"""

from __future__ import annotations

from .. import CUES, DRUMS, LYRIC, VideoType
from .build import build as _build, verify as _verify
from .params import Beat, Depth, Look, Params, Stage, Travel

TYPE = VideoType(
    slug="approach",
    name="Approach",
    description="the words travel out of the distance and past the camera",
    params_cls=Params,
    family=LYRIC,
    needs=frozenset({CUES, DRUMS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Stage", "Travel", "Depth", "Look", "Beat"]
