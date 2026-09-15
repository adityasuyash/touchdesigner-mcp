"""Construct the longhand network.

One Text TOP reading a Specification DAT, which is what lets every word sit at
its own pixel coordinate -- the only way to place glyphs freely without
instancing, which is unsupported on some of the Macs this has to run on.

    v7_script (scriptTOP)   16px of ground; also writes `spec` every frame
    spec (tableDAT)         x, y, text -- one row per visible word
    lh_text (textTOP)       the writing, in a script face
    ...level, bloom, glow, clamp -> out

One Text TOP rather than the depth slabs `approach` needed: every word here is
the same size, because the camera travels ALONG the line rather than toward it.
That is the correction the whole renderer exists for.
"""

from __future__ import annotations

from .._build import (OpSpec, ROOT, apply_exprs, check_types, create_ops,
                      drop_autocreated, wire_ops)


def _rgb(h: float, sat: float) -> tuple[float, float, float]:
    h = (h % 1.0) * 6.0
    i = int(h)
    f = h - i
    p, q, t = 0.0, 1.0 - f, f
    r, g, b = ((1.0, t, p), (q, 1.0, p), (p, 1.0, t),
               (p, q, 1.0), (t, p, 1.0), (1.0, p, q))[i % 6]
    return ((1.0 - sat) + sat * r, (1.0 - sat) + sat * g,
            (1.0 - sat) + sat * b)


def network(cfg) -> list[OpSpec]:
    s, lk = cfg.stage, cfg.look
    frame = {"outputresolution": "custom", "resolutionw": s.width,
             "resolutionh": s.height, "resmult": False}
    ink = _rgb(lk.hue, lk.sat)

    return [
        OpSpec("audio", "audiofileinCHOP", (-1600, 200),
               params={"file": cfg.track.instrumental or cfg.track.source or "",
                       "play": True, "repeat": False}),

        OpSpec("lyrics", "tableDAT", (-1600, -300), preserve=True),
        OpSpec("drums", "tableDAT", (-1600, -400), preserve=True),
        OpSpec("params", "textDAT", (-1600, -420), preserve=True),
        OpSpec("v7_script_callbacks", "textDAT", (-1600, -540), preserve=True),
        OpSpec("spec", "tableDAT", (-1600, -660), preserve=True),

        OpSpec("v7_script", "scriptTOP", (-1200, -400),
               params={"callbacks": "v7_script_callbacks", "resolutionw": 16,
                       "resolutionh": 16, "resmult": False,
                       "format": "rgba32float"}),
        OpSpec("lh_ground", "levelTOP", (-1000, -400),
               params={**frame, "fillmode": "fill"}, inputs=["v7_script"]),

        OpSpec("lh_text", "textTOP", (-1000, -700), params={
            **frame, "font": s.font, "text": "", "specdat": "spec",
            "alignx": "center", "aligny": "center",
            # Points is the default and follows the display's DPI; pixels is the
            # only unit that means the same thing on two machines.
            "fontsizexunit": "pixels", "fontsizeyunit": "pixels",
            "positionunit": "pixels",
            "fontsizex": s.size, "fontsizey": s.size,
            "fontcolorr": round(ink[0], 4), "fontcolorg": round(ink[1], 4),
            "fontcolorb": round(ink[2], 4),
            "bgcolorr": 0.0, "bgcolorg": 0.0, "bgcolorb": 0.0, "bgalpha": 0.0}),
        OpSpec("lh_text_l", "levelTOP", (-800, -700),
               params={**frame, "brightness1": lk.peak}, inputs=["lh_text"]),

        OpSpec("lh_sum1", "compositeTOP", (-600, -400),
               params={**frame, "operand": "add"},
               inputs=["lh_text_l", "lh_ground"]),

        OpSpec("lh_bloom", "blurTOP", (-600, -150),
               params={**frame, "size": lk.bloom}, inputs=["lh_text_l"]),
        OpSpec("lh_bloom_l", "levelTOP", (-400, -150),
               params={**frame, "brightness1": lk.glow}, inputs=["lh_bloom"]),
        OpSpec("lh_sum2", "compositeTOP", (-400, -400),
               params={**frame, "operand": "add"},
               inputs=["lh_sum1", "lh_bloom_l"]),

        # nothing may exceed white; a Level TOP remaps rather than clamps
        OpSpec("lh_white", "constantTOP", (-400, -650), params=frame),
        OpSpec("lh_clamp", "compositeTOP", (-200, -400),
               params={**frame, "operand": "minimum"},
               inputs=["lh_sum2", "lh_white"]),
        OpSpec("out", "nullTOP", (0, -400), params={"resmult": False},
               inputs=["lh_clamp"]),
    ]


def build(client, cfg, progress=None, container: str = ROOT,
          push: bool = True, calibrate: bool = True) -> dict:
    """Put the network into TouchDesigner.

    `calibrate` is accepted and ignored: the glyph metrics the grid renderers
    solve for do not arise here, because the Specification DAT places every
    word at a pixel coordinate this script computed.
    """
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
