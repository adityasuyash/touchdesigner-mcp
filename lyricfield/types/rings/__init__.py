"""Rings: the beat as circles leaving the centre.

The first beatsync renderer here that is not a character field. `pulse_grid`
and `swell` are the same 24x24 grid as `lyric_grid` -- five of the seven styles
between them even share one glyph set -- so they could only ever differ in tint
and timing. This one runs its Script TOP at frame resolution and writes pixels:
a kick is born as a ring and expands until it leaves, a snare throws spokes, the
hi-hats turn a fine grain around the middle.

Curved, soft and centred, which is the geometric opposite of a lattice. Needs no
lyrics.
"""

from __future__ import annotations

from .. import BEATSYNC, DRUMS, VideoType
from .build import build as _build, verify as _verify
from .params import Beat, Frame, Grain, Look, Params, Ring, Spoke

TYPE = VideoType(
    slug="rings",
    name="Rings",
    description="the beat as rings leaving the centre; no lyrics needed",
    params_cls=Params,
    family=BEATSYNC,
    needs=frozenset({DRUMS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Frame", "Ring", "Spoke", "Grain", "Look", "Beat"]
