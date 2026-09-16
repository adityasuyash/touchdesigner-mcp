"""Longhand: handwritten lyrics in a volume, and a camera drifting through it.

From the Chainsmokers' "Closer" lyric video, which the sources describe as
"live action footage compiled with lyrics that fly through 3d space" over what
began as a practical effect -- text written on paper and filmed. The footage
half is out of reach here; the handwriting, the depth and the motion blur are
what make it recognisable, and those are reachable.

It has been read wrong twice. `approach` took it for a flight down a tunnel and
flew words at the camera; `longhand` then took it for a pan along one flat
written line. It is neither: the words hold still, spread through a volume, and
the eye wanders among them.

Every word is placed once, from a pure function of its index, and only the
camera moves -- eased toward whichever word is being sung and never arriving
before the next one lands, with a slow wander on top so it is never quite
still. Perspective is quantised into slabs because a Text TOP has one font size
for its whole Specification DAT; see `build.py`. Needs lyrics.
"""

from __future__ import annotations

from .. import CUES, DRUMS, LYRIC, VideoType
from .build import build as _build, verify as _verify
from .params import Beat, Blur, Camera, Depth, Look, Params, Stage, Volume

TYPE = VideoType(
    slug="longhand",
    name="Longhand",
    description="handwritten lyrics scattered through space, the camera "
                "drifting between them",
    params_cls=Params,
    family=LYRIC,
    needs=frozenset({CUES, DRUMS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Stage", "Volume", "Camera", "Depth", "Blur",
           "Look", "Beat"]
