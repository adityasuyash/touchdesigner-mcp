"""Construct the window network.

    v7_script (scriptTOP)  the moving field, at `scale` of the frame
    win_up (levelTOP)      up to full size
    win_text (textTOP)     the line being sung, white, from the `line` DAT
    win_dark (constantTOP) the near-black everything outside the letters sits in
    win_matte (matteTOP)   the field, through the type, over the dark
    ...bloom, glow, clamp -> out

The Matte TOP is the whole idea: it composites input1 over input2 using input3
as the matte, so "the letters are a hole onto moving light" is one operator
rather than a shader.
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
    # Empty `text`, pixels not points: both learned from monument, where the
    # Text TOP drew its own inline string and sized itself by the display's DPI.
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
        OpSpec("win_up", "levelTOP", (-1000, -400),
               params={**frame, "fillmode": "fill"}, inputs=["v7_script"]),

        OpSpec("win_text", "textTOP", (-1000, -700), params=text),
        OpSpec("win_dark", "constantTOP", (-1000, -150),
               params={**frame, "colorr": 0.0, "colorg": 0.0, "colorb": 0.0}),

        # field over dark, cut by the type
        OpSpec("win_matte", "matteTOP", (-700, -400), params=frame,
               inputs=["win_up", "win_dark", "win_text"]),

        OpSpec("win_bloom", "blurTOP", (-500, -150),
               params={**frame, "size": lk.bloom}, inputs=["win_matte"]),
        OpSpec("win_bloom_l", "levelTOP", (-300, -150),
               params={**frame, "brightness1": lk.glow}, inputs=["win_bloom"]),
        OpSpec("win_sum", "compositeTOP", (-300, -400),
               params={**frame, "operand": "add"},
               inputs=["win_matte", "win_bloom_l"]),

        OpSpec("win_white", "constantTOP", (-300, -650), params=frame),
        OpSpec("win_clamp", "compositeTOP", (-100, -400),
               params={**frame, "operand": "minimum"},
               inputs=["win_sum", "win_white"]),
        OpSpec("out", "nullTOP", (100, -400), params={"resmult": False},
               inputs=["win_clamp"]),
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
