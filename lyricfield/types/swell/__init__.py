"""Swell: the beat as weight and coverage, with no words at all.

The second beatsync renderer, and pointedly not a second look at the first one.
`pulse_grid` holds a fixed scatter of glyphs and lights parts of it; `swell`
holds one coverage number and moves that, so the field thickens and thins. Cells
fill in on the downbeat and step up the glyph ramp `.:-=+*#`, then thin back out
across the bar.

Because it expresses the beat as coverage rather than luminance, the dim layer
never leaves its own brightness band -- so the stacking rule that constrains
every other renderer cannot be breached here, and the glow chain amplifies the
shape rather than clipping it.

It is also the first renderer to use the three measured facts every beatsync
type had been ignoring: it is sparse before `kick_in`, opens up at `high_in`,
and thins away over the last seconds of `duration`, so the piece has a
beginning, an arrival and an ending.
"""

from __future__ import annotations

from .. import BEATSYNC, DRUMS, VideoType
from .build import build as _build, verify as _verify
from .params import Analysis, Grid, Look, Params, Swell

TYPE = VideoType(
    slug="swell",
    name="Swell",
    description="the beat as weight and coverage across a glyph ramp; "
                "no lyrics needed",
    params_cls=Params,
    family=BEATSYNC,
    # The drums alone; see pulse_grid for why the raw mix was not enough.
    needs=frozenset({DRUMS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Grid", "Look", "Analysis", "Swell"]
