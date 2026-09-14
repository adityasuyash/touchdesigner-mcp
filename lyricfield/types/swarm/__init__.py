"""Swarm: words fly in, settle, and are knocked apart.

Physical, but not a physical *simulation*. Bullet and the Particle SOP step per
cook, so a dropped frame or a seek changes what they produce and a song will not
render the same way twice. This runs a twenty-line spring-damper from the line's
own start on every frame instead -- a handful of words over a few hundred fixed
steps, which costs nothing -- so a frame is a pure function of its timestamp.

Each word is pulled toward its place in the line, thrown in from a direction
decided by its index, and shoved outward by every kick that has landed since the
line appeared.
"""

from __future__ import annotations

from .. import CUES, DRUMS, INSTRUMENTAL, LYRIC, VideoType
from .build import build as _build, verify as _verify
from .params import Beat, Burst, Flight, Frame, Line, Look, Params

TYPE = VideoType(
    slug="swarm",
    name="Swarm",
    description="words that fly in, settle, and scatter on the beat",
    params_cls=Params,
    family=LYRIC,
    needs=frozenset({INSTRUMENTAL, CUES, DRUMS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Frame", "Flight", "Burst", "Line", "Look", "Beat"]
