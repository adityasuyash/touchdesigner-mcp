"""Strata: the beat as solid bands, played one at a time.

The straight, stacked, hard-edged answer to `rings`, which is curved, centred
and soft. A kick slams one band to full and it falls back; the next kick takes
the next band, so the stack is played rather than flashed. A snare shears the
whole thing sideways, alternate bands opposite ways. The hi-hats flicker in the
gaps.

Two beat renderers a viewer could confuse would be two renderers doing one job,
which is the thing this pass exists to undo. Needs no lyrics.
"""

from __future__ import annotations

from .. import BEATSYNC, DRUMS, VideoType
from .build import build as _build, verify as _verify
from .params import Band, Beat, Flicker, Frame, Look, Params, Shear

TYPE = VideoType(
    slug="strata",
    name="Strata",
    description="the beat as hard-edged bands, struck one at a time; "
                "no lyrics needed",
    params_cls=Params,
    family=BEATSYNC,
    needs=frozenset({DRUMS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Frame", "Band", "Shear", "Flicker", "Look", "Beat"]
