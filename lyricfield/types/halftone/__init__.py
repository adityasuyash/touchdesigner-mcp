"""Halftone: the beat as a dot screen.

Print reproduction as an aesthetic, and the first renderer here whose ink is a
regular lattice rather than a stroke or a glyph. Tone is carried by the size of
each dot, not its brightness -- which is what separates a halftone from a grid
of flickering points -- and three separations are screened at different angles
so they beat against each other into a rosette.

Closest neighbour is `rings`, and they are geometric opposites: rings are
concentric and continuous, this is uniform and discrete. Needs no lyrics.
"""

from __future__ import annotations

from .. import BEATSYNC, DRUMS, VideoType
from .build import build as _build, verify as _verify
from .params import Beat, Frame, Ink, Look, Params, Screen, Tone

TYPE = VideoType(
    slug="halftone",
    name="Halftone",
    description="the beat as a printed dot screen; no lyrics needed",
    params_cls=Params,
    family=BEATSYNC,
    needs=frozenset({DRUMS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Frame", "Screen", "Tone", "Ink", "Look", "Beat"]
