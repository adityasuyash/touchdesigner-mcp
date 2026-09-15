"""Longhand: a camera travelling a written line.

From the Chainsmokers' "Closer" lyric video. It replaces `approach`, which was
built from the same reference and read it wrong: that flew words at the camera
through depth slabs, and the video pans along one long handwritten string of the
lyrics, word to word, with the words either side trailing off.

Every word is laid out once and the camera moves; the camera is always still
travelling when the next word lands, which is what keeps it floating rather
than reading as a slideshow. Needs lyrics.
"""

from __future__ import annotations

from .. import CUES, DRUMS, LYRIC, VideoType
from .build import build as _build, verify as _verify
from .params import Beat, Camera, Line, Look, Params, Stage

TYPE = VideoType(
    slug="longhand",
    name="Longhand",
    description="a camera drifting along one long handwritten line of the lyrics",
    params_cls=Params,
    family=LYRIC,
    needs=frozenset({CUES, DRUMS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Stage", "Line", "Camera", "Look", "Beat"]
