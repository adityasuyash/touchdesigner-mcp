"""Construct the halftone network.

Short, because the Script TOP *is* the picture. All the network does is take the
dots up to frame size and put a halo on them.

    v7_script (scriptTOP)   the screened field, at `scale` of the frame
    ht_up (levelTOP)        up to full size
    ...bloom, glow, clamp -> out

The scale-up is deliberately NOT smoothed: a halftone whose dots have been
interpolated into soft blobs is no longer a halftone. `nearest` keeps the edge
the field drew, and the bloom afterwards is what makes it glow rather than the
resampler blurring it by accident.
"""

from __future__ import annotations

from .._build import (OpSpec, ROOT, apply_exprs, check_types, create_ops,
                      drop_autocreated, wire_ops)


def network(cfg) -> list[OpSpec]:
    f, lk = cfg.frame, cfg.look
    frame = {"outputresolution": "custom", "resolutionw": f.width,
             "resolutionh": f.height, "resmult": False}
    fw = max(8, int(f.width * f.scale))
    fh = max(8, int(f.height * f.scale))

    return [
        OpSpec("audio", "audiofileinCHOP", (-1600, 200),
               params={"file": cfg.track.instrumental or cfg.track.source or "",
                       "play": True, "repeat": False}),

        OpSpec("drums", "tableDAT", (-1600, -400), preserve=True),
        OpSpec("params", "textDAT", (-1600, -420), preserve=True),
        OpSpec("v7_script_callbacks", "textDAT", (-1600, -540), preserve=True),

        OpSpec("v7_script", "scriptTOP", (-1200, -400),
               params={"callbacks": "v7_script_callbacks", "resolutionw": fw,
                       "resolutionh": fh, "resmult": False,
                       "format": "rgba32float"}),
        OpSpec("ht_up", "levelTOP", (-1000, -400),
               params={**frame, "fillmode": "fill",
                       "inputfiltertype": "nearest"}, inputs=["v7_script"]),

        OpSpec("ht_bloom", "blurTOP", (-800, -150),
               params={**frame, "size": lk.bloom}, inputs=["ht_up"]),
        OpSpec("ht_bloom_l", "levelTOP", (-600, -150),
               params={**frame, "brightness1": lk.glow}, inputs=["ht_bloom"]),
        OpSpec("ht_sum", "compositeTOP", (-400, -400),
               params={**frame, "operand": "add"},
               inputs=["ht_up", "ht_bloom_l"]),

        # nothing may exceed white; a Level TOP remaps rather than clamps
        OpSpec("ht_white", "constantTOP", (-400, -650), params=frame),
        OpSpec("ht_clamp", "compositeTOP", (-200, -400),
               params={**frame, "operand": "minimum"},
               inputs=["ht_sum", "ht_white"]),
        OpSpec("out", "nullTOP", (0, -400), params={"resmult": False},
               inputs=["ht_clamp"]),
    ]


def build(client, cfg, progress=None, container: str = ROOT,
          push: bool = True, calibrate: bool = True) -> dict:
    """Put the network into TouchDesigner. `calibrate` is accepted and ignored:
    there is no type here whose metrics need solving."""
    say = progress or (lambda m: None)
    specs = network(cfg)
    out: dict = {}
    say(f"creating {len(specs)} operators")
    out["created"] = create_ops(client, specs, progress=say, container=container)
    out["wired"] = wire_ops(client, specs, progress=say, container=container)
    out["exprs"] = apply_exprs(client, specs, progress=say, container=container)
    out["dropped"] = drop_autocreated(client, specs, progress=say,
                                      container=container)
    if push:
        from ... import sync
        say("pushing params and the field script")
        sync.push_params(client, cfg)
        sync.push_field(client, cfg)
    return out


def verify(client, cfg, container: str = ROOT) -> list[str]:
    specs = network(cfg)
    return check_types(client, specs)
