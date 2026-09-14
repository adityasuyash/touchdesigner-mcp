"""Glitch: the words, torn.

Scanlines, channels pulled apart, blocks of the picture displaced -- the
corruption half of the vaporwave vocabulary, where `horizon` has the neon half.
Nothing else here damages its own output; every other renderer draws a clean
picture and lights it.

The tear is done with a Remap TOP rather than by drawing displaced rectangles,
so it moves the pixels that are already there. Needs lyrics.
"""

from __future__ import annotations

from .. import CUES, DRUMS, LYRIC, VideoType
from .build import build as _build, verify as _verify
from .params import Beat, Lines, Look, Params, Split, Stage, Tear

TYPE = VideoType(
    slug="glitch",
    name="Glitch",
    description="the words torn sideways, channels split, scanlines rolling",
    params_cls=Params,
    family=LYRIC,
    needs=frozenset({CUES, DRUMS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Stage", "Tear", "Split", "Lines", "Look", "Beat"]
