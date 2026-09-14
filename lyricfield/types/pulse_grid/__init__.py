"""Pulse grid: the beat as light, with no words at all.

The same dense character field as `lyric_grid`, expressing the same thing --
brightness, never motion or scale -- but with nothing to read. A crest sweeps
the field in time with the measured beat grid, kicks open radial ripples,
snares scatter sparks, and the hi-hats shimmer across the whole thing.

Needs no lyrics, which is the point: an instrumental used to render a black
frame for its entire length, because the only renderer that existed drew the
song's own words and there were none.
"""

from __future__ import annotations

from .. import BEATSYNC, DRUMS, VideoType
from .build import build as _build, verify as _verify
from .params import Analysis, Grid, Look, Params, Pulse

TYPE = VideoType(
    slug="pulse_grid",
    name="Pulse grid",
    description="the beat as light across a character field; no lyrics needed",
    params_cls=Params,
    family=BEATSYNC,
    # The drums, and nothing else: no words to transcribe, no vocal to isolate.
    # It asked for the raw mix until the detection was measured -- a kick
    # detector on a full mix fires on the bassline, and its events had a phase
    # concentration within the beat of 0.12, which is uniform.
    needs=frozenset({DRUMS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Grid", "Look", "Analysis", "Pulse"]
