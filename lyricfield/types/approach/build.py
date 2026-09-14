"""Construct the approach network.

One Text TOP per depth slab, each fixed at the size that depth calls for, each
reading its own Specification DAT -- which is what makes per-word perspective
possible at all, because a Text TOP has one font size for its whole table.

    v7_script (scriptTOP)    16px of ground; also writes every spec table
    spec0..specN (tableDAT)  one per slab, nearest first
    ap_text0..N (textTOP)    the slabs, sizes from `params.slab_sizes`
    ap_haze (blurTOP)        the farthest slab only: distance costs focus
    ...added together, bloomed, clamped -> out

The slabs are composited FARTHEST FIRST, so a near word covers a far one rather
than the other way round. That ordering is the only thing here that has to be
right for the depth to read.
"""

from __future__ import annotations

from .._build import (OpSpec, ROOT, apply_exprs, check_types, create_ops,
                      drop_autocreated, wire_ops)
from .params import slab_depths


def network(cfg) -> list[OpSpec]:
    s, tr, d, lk = cfg.stage, cfg.travel, cfg.depth, cfg.look
    frame = {"outputresolution": "custom", "resolutionw": s.width,
             "resolutionh": s.height, "resmult": False}
    # `travel.size_at_one` is the font size at depth 1.0; a slab standing at
    # depth z therefore draws at size_at_one/z. The depths come from
    # `params.slab_depths`, which the field script mirrors -- if the two ever
    # disagreed a word would be drawn at a size that did not match its depth,
    # and the perspective would simply be wrong with nothing to show for it.
    sizes = [tr.size_at_one / z
             for z in slab_depths(cfg.params if hasattr(cfg, "params") else cfg)]
    n = len(sizes)

    def text_par(px, spec):
        return {**frame, "font": s.font, "text": "", "specdat": spec,
                "alignx": "center", "aligny": "center",
                # Points is the default and follows the display's DPI; pixels is
                # the only unit that means the same thing on two machines.
                "fontsizexunit": "pixels", "fontsizeyunit": "pixels",
                "positionunit": "pixels",
                "fontsizex": px, "fontsizey": px,
                "fontcolorr": 1.0, "fontcolorg": 1.0, "fontcolorb": 1.0,
                "bgcolorr": 0.0, "bgcolorg": 0.0, "bgcolorb": 0.0,
                "bgalpha": 0.0}

    specs = [
        OpSpec("audio", "audiofileinCHOP", (-1600, 200),
               params={"file": cfg.track.instrumental or cfg.track.source or "",
                       "play": True, "repeat": False}),

        OpSpec("lyrics", "tableDAT", (-1600, -300), preserve=True),
        OpSpec("drums", "tableDAT", (-1600, -400), preserve=True),
        OpSpec("params", "textDAT", (-1600, -420), preserve=True),
        OpSpec("v7_script_callbacks", "textDAT", (-1600, -540), preserve=True),

        OpSpec("v7_script", "scriptTOP", (-1200, -400),
               params={"callbacks": "v7_script_callbacks", "resolutionw": 16,
                       "resolutionh": 16, "resmult": False,
                       "format": "rgba32float"}),
        OpSpec("ap_ground", "levelTOP", (-1000, -400),
               params={**frame, "fillmode": "fill"}, inputs=["v7_script"]),
    ]

    # Farthest first, so the composite stacks near over far.
    order = list(range(n - 1, -1, -1))
    prev = None
    for k, i in enumerate(order):
        y = -900 + k * 120
        specs.append(OpSpec("spec%d" % i, "tableDAT", (-1600, y - 40),
                            preserve=True))
        specs.append(OpSpec("ap_text%d" % i, "textTOP", (-1200, y),
                            params=text_par(round(sizes[i], 2), "spec%d" % i)))
        src = "ap_text%d" % i
        if i == n - 1 and d.haze > 0:
            specs.append(OpSpec("ap_haze", "blurTOP", (-1050, y),
                                params={**frame, "size": d.haze},
                                inputs=[src]))
            src = "ap_haze"
        # Fog: the farthest slab is dimmest. Geometric between 1 and `fog`, to
        # match the geometric depth spacing -- linear made the near slabs all
        # look the same brightness.
        f = d.fog ** (i / max(1, n - 1))
        specs.append(OpSpec("ap_lvl%d" % i, "levelTOP", (-900, y),
                            params={**frame, "brightness1": round(
                                lk.peak * f, 4)},
                            inputs=[src]))
        cur = "ap_lvl%d" % i
        if prev is None:
            prev = cur
        else:
            name = "ap_over%d" % i
            specs.append(OpSpec(name, "compositeTOP", (-700, y),
                                params={**frame, "operand": "over"},
                                inputs=[cur, prev]))
            prev = name

    specs += [
        OpSpec("ap_sum1", "compositeTOP", (-500, -400),
               params={**frame, "operand": "add"},
               inputs=[prev, "ap_ground"]),

        OpSpec("ap_bloom", "blurTOP", (-500, -150),
               params={**frame, "size": lk.bloom}, inputs=[prev]),
        OpSpec("ap_bloom_l", "levelTOP", (-300, -150),
               params={**frame, "brightness1": lk.glow}, inputs=["ap_bloom"]),
        OpSpec("ap_sum2", "compositeTOP", (-300, -400),
               params={**frame, "operand": "add"},
               inputs=["ap_sum1", "ap_bloom_l"]),

        # nothing may exceed white; a Level TOP remaps rather than clamps
        OpSpec("ap_white", "constantTOP", (-300, -650), params=frame),
        OpSpec("ap_clamp", "compositeTOP", (-100, -400),
               params={**frame, "operand": "minimum"},
               inputs=["ap_sum2", "ap_white"]),
        OpSpec("out", "nullTOP", (100, -400), params={"resmult": False},
               inputs=["ap_clamp"]),
    ]
    return specs


def build(client, cfg, progress=None, container: str = ROOT,
          push: bool = True, calibrate: bool = True) -> dict:
    """Put the network into TouchDesigner.

    `calibrate` is accepted and ignored: the glyph metrics the grid renderers
    have to solve for do not arise here, because a Specification DAT places
    every word at a pixel coordinate this script computed.
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
    specs = network(cfg)
    return check_types(client, specs)
