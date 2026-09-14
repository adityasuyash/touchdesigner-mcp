"""Monument: one word, filling the frame, struck on its cue.

The first renderer here that is not a grid of glyphs. `lyric_grid` and the two
beatsync types are one network -- a character field at one pixel per cell --
so every style any of them could ever have was that same picture in a different
tint. This one draws a single word as large as it will go, cuts to the next on
cue, and leaves the one before behind it as a dimmer, larger afterimage.

Needs lyrics, obviously: the word is the whole subject. It asks for drums as
well, but only to move the room -- a kick lifts the ground the type sits on,
never the type, because the word belongs to the cue table and the room belongs
to the beat.
"""

from __future__ import annotations

from .. import CUES, DRUMS, INSTRUMENTAL, LYRIC, VideoType
from .build import build as _build, verify as _verify
from .params import Beat, Look, Params, Stage, Word

TYPE = VideoType(
    slug="monument",
    name="Monument",
    description="one word at a time, filling the frame, cut on the beat",
    params_cls=Params,
    family=LYRIC,
    # The cue table is the subject; the drums move the ground behind it; a
    # clean instrumental because vocals pollute onset detection.
    needs=frozenset({INSTRUMENTAL, CUES, DRUMS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Stage", "Word", "Look", "Beat"]
