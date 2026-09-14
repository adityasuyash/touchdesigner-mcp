"""Construct the horizon network.

    v7_script (scriptTOP)  the scene: sky, sun and the floor in perspective
    hz_up (levelTOP)       up to frame size
    hz_text (textTOP)      the line, white, over the scene
    ...add, bloom, glow, clamp -> out

The type is composited over rather than matted through: this renderer draws a
place, and the words stand in it.
"""

from __future__ import annotations

from .._build import (OpSpec, ROOT, apply_exprs, check_types, create_ops,
                      drop_autocreated, wire_ops)


def network(cfg) -> list[OpSpec]:
    f, ln, lk = cfg.frame, cfg.line, cfg.look
    frame = {"outputresolution": "custom", "resolutionw": f.width,
             "resolutionh": f.height, "resmult": False}
    fw = max(8, int(f.width * f.scale))
    fh = max(8, int(f.height * f.scale))
    text = {**frame, "font": ln.font, "alignx": "center", "aligny": "center",
            "text": "", "dat": "line",
            "fontsizexunit": "pixels", "fontsizeyunit": "pixels",
            "positionunit": "pixels",
            "fontsizex": ln.size, "fontsizey": ln.size,
            "fontcolorr": 1.0, "fontcolorg": 1.0, "fontcolorb": 1.0,
            "bgcolorr": 0.0, "bgcolorg": 0.0, "bgcolorb": 0.0, "bgalpha": 0.0}

    return [
        OpSpec("audio", "audiofileinCHOP", (-1600, 200),
               params={"file": cfg.track.instrumental or cfg.track.source or "",
                       "play": True, "repeat": False}),
        OpSpec("lyrics", "tableDAT", (-1600, -300), preserve=True),
        OpSpec("drums", "tableDAT", (-1600, -400), preserve=True),
        OpSpec("params", "textDAT", (-1600, -420), preserve=True),
        OpSpec("v7_script_callbacks", "textDAT", (-1600, -540), preserve=True),
        OpSpec("line", "textDAT", (-1600, -660), preserve=True),

        OpSpec("v7_script", "scriptTOP", (-1200, -400),
               params={"callbacks": "v7_script_callbacks", "resolutionw": fw,
                       "resolutionh": fh, "resmult": False,
                       "format": "rgba32float"}),
        OpSpec("hz_up", "levelTOP", (-1000, -400),
               params={**frame, "fillmode": "fill"}, inputs=["v7_script"]),

        OpSpec("hz_text", "textTOP", (-1000, -700), params=text),
        OpSpec("hz_scene", "compositeTOP", (-700, -400),
               params={**frame, "operand": "add"},
               inputs=["hz_up", "hz_text"]),

        OpSpec("hz_bloom", "blurTOP", (-500, -150),
               params={**frame, "size": lk.bloom}, inputs=["hz_scene"]),
        OpSpec("hz_bloom_l", "levelTOP", (-300, -150),
               params={**frame, "brightness1": lk.glow}, inputs=["hz_bloom"]),
        OpSpec("hz_sum", "compositeTOP", (-300, -400),
               params={**frame, "operand": "add"},
               inputs=["hz_scene", "hz_bloom_l"]),

        OpSpec("hz_white", "constantTOP", (-300, -650), params=frame),
        OpSpec("hz_clamp", "compositeTOP", (-100, -400),
               params={**frame, "operand": "minimum"},
               inputs=["hz_sum", "hz_white"]),
        OpSpec("out", "nullTOP", (100, -400), params={"resmult": False},
               inputs=["hz_clamp"]),
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
