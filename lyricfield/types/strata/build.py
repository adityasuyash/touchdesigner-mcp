"""Construct the strata network.

The same short shape as `rings` -- the Script TOP is the picture -- with one
deliberate difference: the bloom is small. Hard edges and a wide halo fight
each other, and the edge is what this renderer is for.
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
        # `nativeres` would letterbox; `fill` stretches the field to the frame,
        # and since the bands are horizontal the stretch is along their length.
        OpSpec("str_up", "levelTOP", (-1000, -400),
               params={**frame, "fillmode": "fill"}, inputs=["v7_script"]),

        OpSpec("str_bloom", "blurTOP", (-800, -150),
               params={**frame, "size": lk.bloom}, inputs=["str_up"]),
        OpSpec("str_bloom_l", "levelTOP", (-600, -150),
               params={**frame, "brightness1": lk.glow}, inputs=["str_bloom"]),
        OpSpec("str_sum", "compositeTOP", (-400, -400),
               params={**frame, "operand": "add"},
               inputs=["str_up", "str_bloom_l"]),

        OpSpec("str_white", "constantTOP", (-400, -650), params=frame),
        OpSpec("str_clamp", "compositeTOP", (-200, -400),
               params={**frame, "operand": "minimum"},
               inputs=["str_sum", "str_white"]),
        OpSpec("out", "nullTOP", (0, -400), params={"resmult": False},
               inputs=["str_clamp"]),
    ]


def build(client, cfg, progress=None, container: str = ROOT,
          push: bool = True, calibrate: bool = True) -> dict:
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
    return check_types(client, network(cfg))
