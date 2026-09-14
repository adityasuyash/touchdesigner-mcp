"""Scope: one continuous curve, glowing, on black.

The third beat renderer, and deliberately unlike either of the others: `rings`
is soft and radial, `strata` hard and stacked, this a single bright line with a
phosphor trail and nothing else in the frame. It reads as an instrument rather
than as a picture.

Its trail is drawn from the curve's own recent past rather than accumulated in
a buffer, so a frame is a pure function of its own timestamp. Seeking to the
middle of a song gives exactly the frame a full playthrough would -- which is
the difference between a renderer that re-renders and one that only looks right
if you watched it get there.
"""

from __future__ import annotations

from .. import BEATSYNC, DRUMS, VideoType
from .build import build as _build, verify as _verify
from .params import Beat, Curve, Frame, Look, Params, Trail

TYPE = VideoType(
    slug="scope",
    name="Scope",
    description="one glowing curve with a phosphor trail; no lyrics needed",
    params_cls=Params,
    family=BEATSYNC,
    needs=frozenset({DRUMS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Frame", "Curve", "Trail", "Look", "Beat"]
