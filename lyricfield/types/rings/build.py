"""Construct the rings network.

Short, because the Script TOP *is* the picture here. The grid types need two
Text TOPs and a compositing chain to turn a cell array into glyphs; this one
writes pixels, so all the network does is take them up to frame size and put a
halo on them.

    v7_script (scriptTOP)   the field, at `scale` of the frame
    rng_up (levelTOP)       up to full size
    ...bloom, glow, clamp -> out
"""

from __future__ import annotations

from .._build import (OpSpec, ROOT, apply_exprs, check_types, create_ops,
                      drop_autocreated, wire_ops)


def network(cfg) -> list[OpSpec]:
    f, lk = cfg.frame, cfg.look
    frame = {"outputresolution": "custom", "resolutionw": f.width,
             "resolutionh": f.height, "resmult": False}
    # The field is computed small and scaled up. Everything drawn here is soft,
    # so the only thing the saved pixels cost is speed.
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
        OpSpec("rng_up", "levelTOP", (-1000, -400),
               params={**frame, "fillmode": "fill"}, inputs=["v7_script"]),

        OpSpec("rng_bloom", "blurTOP", (-800, -150),
               params={**frame, "size": lk.bloom}, inputs=["rng_up"]),
        OpSpec("rng_bloom_l", "levelTOP", (-600, -150),
               params={**frame, "brightness1": lk.glow}, inputs=["rng_bloom"]),
        OpSpec("rng_sum", "compositeTOP", (-400, -400),
               params={**frame, "operand": "add"},
               inputs=["rng_up", "rng_bloom_l"]),

        # nothing may exceed white; a Level TOP remaps rather than clamps
        OpSpec("rng_white", "constantTOP", (-400, -650), params=frame),
        OpSpec("rng_clamp", "compositeTOP", (-200, -400),
               params={**frame, "operand": "minimum"},
               inputs=["rng_sum", "rng_white"]),
        OpSpec("out", "nullTOP", (0, -400), params={"resmult": False},
               inputs=["rng_clamp"]),
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
