"""Longhand: lyrics lettered by hand over footage.

From the Chainsmokers' "Closer" lyric video -- the most-watched lyric video
there is -- built from frames of it rather than from descriptions of it. Thick
white marker lettering, flat and large over live action, a lyric phrase at a
time, with mixed caps and lowercase inside a single word and a baseline that
wanders.

It has been read wrong three times, in three different directions: `approach`
flew words at the camera, a first `longhand` panned along one written line, a
second scattered them through a volume with a camera drifting between them. All
three lean on one published sentence about lyrics that "fly through 3d space",
which describes a single aerial shot where the lettering is tracked onto a
landscape. The type never moves through space. It sits there, and the drone
moves.

The footage is the song's own (`Track.plate`) when it has any, and a generated
stand-in when it does not -- which is what the gallery tile is recorded
against, a preview carrying nothing of whichever song is loaded. Needs lyrics.
"""

from __future__ import annotations

from .. import CUES, DRUMS, LYRIC, VideoType
from .build import build as _build, verify as _verify
from .params import Beat, Ground, Hand, Line, Look, Params, Stage

TYPE = VideoType(
    slug="longhand",
    name="Longhand",
    description="the lyrics lettered by hand, big, over your footage",
    params_cls=Params,
    family=LYRIC,
    needs=frozenset({CUES, DRUMS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Stage", "Line", "Hand", "Ground", "Look",
           "Beat"]
