"""Construct the swell network.

There is nothing here that `lyric_grid` does not already construct, for the same
reason `pulse_grid`'s build says so: all three types draw a character grid at one
pixel per cell, composite a dim layer and a bold lit layer, and push the result
through the same glow and bloom chain -- and that network is generated from
`grid`, `look`, `analysis` and the track, every one of which this type declares
by sharing the same dataclasses.

What differs between the types is the field script, and `build` pushes whichever
script the active type declares.
"""

from __future__ import annotations

from ..lyric_grid.build import ROOT, build as _build, verify as _verify


def build(client, cfg, progress=None, container: str = ROOT,
          push: bool = True, calibrate: bool = True) -> dict:
    return _build(client, cfg, progress=progress, container=container,
                  push=push, calibrate=calibrate)


def verify(client, cfg, container: str = ROOT) -> list[str]:
    return _verify(client, cfg, container)
