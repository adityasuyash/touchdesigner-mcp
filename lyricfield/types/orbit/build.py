"""Construct the orbit network.

    spec (tableDAT)        one row per character: x, y, text
    orb_text (textTOP)     reads that through `specdat`, not `dat`
    v7_script (scriptTOP)  the ground, and the hand that writes the table
    ...level, bloom, glow, clamp -> out

`specdat` is the whole point: it places each row at its own pixel coordinate,
which is what lets a line ride a curve instead of sitting in a cell or a block.
"""

from __future__ import annotations

from .._build import (OpSpec, ROOT, apply_exprs, check_types, create_ops,
                      drop_autocreated, wire_ops)


def network(cfg) -> list[OpSpec]:
    f, ln, lk = cfg.frame, cfg.line, cfg.look
    frame = {"outputresolution": "custom", "resolutionw": f.width,
             "resolutionh": f.height, "resmult": False}
    text = {**frame, "font": ln.font, "text": "", "specdat": "spec",
            "alignx": "center", "aligny": "center",
            "fontsizexunit": "pixels", "fontsizeyunit": "pixels",
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
        # Written every frame by the field script: one row per character.
        OpSpec("spec", "tableDAT", (-1600, -660), preserve=True),

        OpSpec("v7_script", "scriptTOP", (-1200, -400),
               params={"callbacks": "v7_script_callbacks", "resolutionw": 16,
                       "resolutionh": 16, "resmult": False,
                       "format": "rgba32float"}),
        OpSpec("orb_ground", "levelTOP", (-1000, -400),
               params={**frame, "fillmode": "fill"}, inputs=["v7_script"]),

        OpSpec("orb_text", "textTOP", (-1000, -700), params=text),
        OpSpec("orb_text_l", "levelTOP", (-800, -700),
               params={**frame, "brightness1": lk.peak}, inputs=["orb_text"]),

        OpSpec("orb_sum1", "compositeTOP", (-600, -400),
               params={**frame, "operand": "add"},
               inputs=["orb_ground", "orb_text_l"]),
        OpSpec("orb_bloom", "blurTOP", (-600, -150),
               params={**frame, "size": lk.bloom}, inputs=["orb_text_l"]),
        OpSpec("orb_bloom_l", "levelTOP", (-400, -150),
               params={**frame, "brightness1": lk.glow}, inputs=["orb_bloom"]),
        OpSpec("orb_sum2", "compositeTOP", (-400, -400),
               params={**frame, "operand": "maximum"},
               inputs=["orb_sum1", "orb_bloom_l"]),

        OpSpec("orb_white", "constantTOP", (-400, -650), params=frame),
        OpSpec("orb_clamp", "compositeTOP", (-200, -400),
               params={**frame, "operand": "minimum"},
               inputs=["orb_sum2", "orb_white"]),
        OpSpec("out", "nullTOP", (0, -400), params={"resmult": False},
               inputs=["orb_clamp"]),
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
