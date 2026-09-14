"""Construct the scope network.

The same short shape as the other pixel renderers, with a generous bloom: a
bare one-pixel line needs it to read as phosphor rather than as a scratch.
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
        OpSpec("scp_up", "levelTOP", (-1000, -400),
               params={**frame, "fillmode": "fill"}, inputs=["v7_script"]),

        # Two blurs: a tight one for the filament and a wide one for the halo
        # around it. One blur gives either a hard line with no bloom or a smear
        # with no line.
        OpSpec("scp_tight", "blurTOP", (-800, -200),
               params={**frame, "size": max(1.0, lk.bloom * 0.2)},
               inputs=["scp_up"]),
        # A blur conserves energy, so spreading a one-pixel filament over four
        # pixels divides its brightness by about fifty and the curve comes back
        # all but invisible. This puts that back.
        OpSpec("scp_tight_l", "levelTOP", (-700, -200),
               params={**frame, "brightness1": 6.0}, inputs=["scp_tight"]),
        OpSpec("scp_wide", "blurTOP", (-800, -50),
               params={**frame, "size": lk.bloom}, inputs=["scp_up"]),
        OpSpec("scp_wide_l", "levelTOP", (-600, -50),
               params={**frame, "brightness1": lk.glow}, inputs=["scp_wide"]),
        OpSpec("scp_sum", "compositeTOP", (-400, -400),
               params={**frame, "operand": "add"},
               inputs=["scp_tight_l", "scp_wide_l"]),

        OpSpec("scp_white", "constantTOP", (-400, -650), params=frame),
        OpSpec("scp_clamp", "compositeTOP", (-200, -400),
               params={**frame, "operand": "minimum"},
               inputs=["scp_sum", "scp_white"]),
        OpSpec("out", "nullTOP", (0, -400), params={"resmult": False},
               inputs=["scp_clamp"]),
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
