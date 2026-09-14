"""Spectrum: the beat as bars.

The most recognisable music visual there is, and the last obvious one missing.
It is also the only renderer here that draws a measurement rather than a
reaction: every other type answers onsets from the drum table, and bars are not
a reaction to the beat, they ARE the spectrum.

That is why it is the only type declaring `BANDS` in its needs -- `bands.tsv`,
measured by `analysis.detect_bands` and pushed like the drums. Needs no lyrics.
"""

from __future__ import annotations

from .. import BANDS, BEATSYNC, DRUMS, VideoType
from .build import build as _build, verify as _verify
from .params import Bars, Beat, Caps, Frame, Look, Params

TYPE = VideoType(
    slug="spectrum",
    name="Spectrum",
    description="the song's own frequency bars, with peak caps; no lyrics needed",
    params_cls=Params,
    family=BEATSYNC,
    needs=frozenset({DRUMS, BANDS}),
    field_file="field.py",
    build=_build,
    verify=_verify,
)

__all__ = ["TYPE", "Params", "Frame", "Bars", "Caps", "Look", "Beat"]
