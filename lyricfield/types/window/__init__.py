"""Window: the words are a hole, and light moves behind them.

The only renderer here where the two halves of this system are one picture.
Everywhere else a song is either words or beat; this one draws a beat-driven
field of drifting bands and lets the lyrics cut it out, so what you read is
type and what you watch move is the drums.

One Matte TOP does the cutting -- input1 over input2 through input3 -- so no
shader is involved and nothing is quantised to a lattice.
"""

from __future__ import annotations

from .. import CUES, DRUMS, INSTRUMENTAL, LYRIC, VideoType
from .build import build as _build, verify as _verify
from .params import Beat, Field, Frame, Line, Look, Params

TYPE = VideoType(
    slug="window",
    name="Window",
    description="the lyrics cut out of moving light; words and beat in one "
                "picture",
    params_cls=Params,
    family=LYRIC,
    needs=frozenset({INSTRUMENTAL, CUES, DRUMS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Frame", "Line", "Field", "Look", "Beat"]
