"""Construct the longhand network.

One Text TOP per depth slab, each fixed at the size that depth calls for, each
reading its own Specification DAT -- which is what makes per-word perspective
possible at all, because a Text TOP has one font size for its whole table.

    v7_script (scriptTOP)   16px of ground; also writes every spec table
    spec0..specN (tableDAT) one per slab, nearest first
    lh_text0..N (textTOP)   the slabs, sizes from `params.slab_depths`
    lh_haze (blurTOP)       the farthest slab only: distance costs focus
    lh_lvl0..N (levelTOP)   the fog: the farthest slab is dimmest
    ...stacked OVER, farthest first
    lh_tap_a/b (transform)  the motion blur, two taps either side of centre
    ...bloomed, clamped -> out

Two things here have to be right or the depth simply does not read, with
nothing on screen to say why:

  * The slabs are composited FARTHEST FIRST, so a near word covers a far one
    rather than the other way round. `over` is correct despite the warning in
    CLAUDE.md that it does nothing over an opaque frame -- these Text TOPs
    carry `bgalpha` 0, so they are transparent between glyphs. The stack goes
    under the ground rather than over it.
  * The font sizes come from `params.slab_depths`, the same list `field.py`
    assigns words from. If the two ever disagreed a word would be drawn at a
    size that did not match its distance.
"""

from __future__ import annotations

from .._build import (OpSpec, ROOT, apply_exprs, check_types, create_ops,
                      drop_autocreated, wire_ops)
from .params import slab_depths


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
    s, d, bl, lk = cfg.stage, cfg.depth, cfg.blur, cfg.look
    frame = {"outputresolution": "custom", "resolutionw": s.width,
             "resolutionh": s.height, "resmult": False}
    ink = _rgb(lk.hue, lk.sat)

    depths = slab_depths(cfg.params if hasattr(cfg, "params") else cfg)
    # `size_at_one` is the font size at depth 1.0, so a slab standing at depth
    # z draws at size_at_one/z. This is the whole of the perspective.
    sizes = [s.size_at_one / z for z in depths]
    n = len(sizes)

    def text_par(px, spec):
        return {**frame, "font": s.font, "text": "", "specdat": spec,
                "alignx": "center", "aligny": "center",
                # Points is the default and follows the display's DPI; pixels
                # is the only unit that means the same thing on two machines.
                "fontsizexunit": "pixels", "fontsizeyunit": "pixels",
                "positionunit": "pixels",
                "fontsizex": round(px, 2), "fontsizey": round(px, 2),
                "fontcolorr": round(ink[0], 4), "fontcolorg": round(ink[1], 4),
                "fontcolorb": round(ink[2], 4),
                "bgcolorr": 0.0, "bgcolorg": 0.0, "bgcolorb": 0.0,
                "bgalpha": 0.0}

    specs = [
        OpSpec("audio", "audiofileinCHOP", (-1800, 200),
               params={"file": cfg.track.instrumental or cfg.track.source or "",
                       "play": True, "repeat": False}),

        OpSpec("lyrics", "tableDAT", (-1800, -300), preserve=True),
        OpSpec("drums", "tableDAT", (-1800, -400), preserve=True),
        OpSpec("params", "textDAT", (-1800, -420), preserve=True),
        OpSpec("v7_script_callbacks", "textDAT", (-1800, -540), preserve=True),

        OpSpec("v7_script", "scriptTOP", (-1400, -400),
               params={"callbacks": "v7_script_callbacks", "resolutionw": 16,
                       "resolutionh": 16, "resmult": False,
                       "format": "rgba32float"}),
        OpSpec("lh_ground", "levelTOP", (-1200, -400),
               params={**frame, "fillmode": "fill"}, inputs=["v7_script"]),
    ]

    # Farthest first, so the composite stacks near over far.
    prev = None
    for k, i in enumerate(range(n - 1, -1, -1)):
        y = -900 - k * 130
        specs.append(OpSpec("spec%d" % i, "tableDAT", (-1800, y - 45),
                            preserve=True))
        specs.append(OpSpec("lh_text%d" % i, "textTOP", (-1400, y),
                            params=text_par(sizes[i], "spec%d" % i)))
        src = "lh_text%d" % i
        if i == n - 1 and d.haze > 0:
            specs.append(OpSpec("lh_haze", "blurTOP", (-1250, y),
                                params={**frame, "size": d.haze},
                                inputs=[src]))
            src = "lh_haze"
        # Fog: the farthest slab is dimmest. Geometric between 1 and `fog`, to
        # match the geometric depth spacing -- linear made the near slabs all
        # look the same brightness.
        f = d.fog ** (i / max(1, n - 1))
        specs.append(OpSpec("lh_lvl%d" % i, "levelTOP", (-1100, y),
                            params={**frame,
                                    "brightness1": round(lk.peak * f, 4)},
                            inputs=[src]))
        cur = "lh_lvl%d" % i
        if prev is None:
            prev = cur
        else:
            name = "lh_over%d" % i
            specs.append(OpSpec(name, "compositeTOP", (-900, y),
                                params={**frame, "operand": "over"},
                                inputs=[cur, prev]))
            prev = name

    # ---- the smear -------------------------------------------------------
    # Three taps of the stack averaged: the middle one undisplaced and two
    # offset either side along the camera's screen velocity, which `field.py`
    # sets each frame. A directional-blur operator would be one node instead of
    # four, but nothing in this repo has used one and its existence cannot be
    # checked without TouchDesigner running; this is built from the transform
    # and composite TOPs every renderer here already leans on, and it is a pure
    # function of the timestamp either way.
    if bl.amount > 0:
        specs += [
            OpSpec("lh_tap_a", "transformTOP", (-700, -700),
                   params={**frame, "tunit": "pixels", "extend": "zero",
                           "tx": 0.0, "ty": 0.0}, inputs=[prev]),
            OpSpec("lh_tap_b", "transformTOP", (-700, -1000),
                   params={**frame, "tunit": "pixels", "extend": "zero",
                           "tx": 0.0, "ty": 0.0}, inputs=[prev]),
            OpSpec("lh_mix1", "compositeTOP", (-550, -700),
                   params={**frame, "operand": "add"},
                   inputs=[prev, "lh_tap_a"]),
            OpSpec("lh_mix2", "compositeTOP", (-550, -850),
                   params={**frame, "operand": "add"},
                   inputs=["lh_mix1", "lh_tap_b"]),
            # A third of three taps: added and then scaled back, so a still
            # frame is exactly as bright as it was before the branch existed.
            OpSpec("lh_smear", "levelTOP", (-550, -1000),
                   params={**frame, "brightness1": round(1.0 / 3.0, 4)},
                   inputs=["lh_mix2"]),
        ]
        lit = "lh_smear"
    else:
        lit = prev

    specs += [
        OpSpec("lh_sum1", "compositeTOP", (-400, -400),
               params={**frame, "operand": "add"},
               inputs=[lit, "lh_ground"]),

        OpSpec("lh_bloom", "blurTOP", (-400, -150),
               params={**frame, "size": lk.bloom}, inputs=[lit]),
        OpSpec("lh_bloom_l", "levelTOP", (-250, -150),
               params={**frame, "brightness1": lk.glow}, inputs=["lh_bloom"]),
        OpSpec("lh_sum2", "compositeTOP", (-250, -400),
               params={**frame, "operand": "add"},
               inputs=["lh_sum1", "lh_bloom_l"]),

        # nothing may exceed white; a Level TOP remaps rather than clamps
        OpSpec("lh_white", "constantTOP", (-250, -650), params=frame),
        OpSpec("lh_clamp", "compositeTOP", (-100, -400),
               params={**frame, "operand": "minimum"},
               inputs=["lh_sum2", "lh_white"]),
        OpSpec("out", "nullTOP", (100, -400), params={"resmult": False},
               inputs=["lh_clamp"]),
    ]
    return specs


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
