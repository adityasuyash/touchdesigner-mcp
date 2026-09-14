"""Construct the glitch network.

    v7_script (scriptTOP)   the MAP: red = where to sample across, green = down,
                            blue = the scanline mask. Eight pixels wide.
    gl_words (textDAT)      the line, assembled as it is sung
    gl_text (textTOP)       that line, drawn once, straight
    gl_remap (remapTOP)     pixels moved by the map -- this is the tear
    gl_plus / gl_minus      the same picture, shifted either way
    gl_split (reorderTOP)   red from one, green from the middle, blue from the
                            other: the channel separation, in a single operator
    gl_mask + gl_lines      the scanlines, multiplied in
    ...bloom, glow, clamp -> out

Two things here are worth knowing before changing any of it.

A Remap TOP takes the picture on input1 and the map on input2, and `horzsource`
/ `vertsource` say which channel of the map carries which coordinate. It moves
the pixels that are there. Drawing displaced rectangles on top instead is the
obvious alternative and it looks like rectangles, not like damage.

A Reorder TOP takes FOUR inputs, which is why the three-way channel split is one
operator rather than a tree of them: red comes from the picture shifted one way,
blue from it shifted the other, green from it left alone.
"""

from __future__ import annotations

from .._build import (OpSpec, ROOT, apply_exprs, check_types, create_ops,
                      drop_autocreated, wire_ops)

MAP_W = 8


def _rgb(h: float, sat: float) -> tuple[float, float, float]:
    """The ink colour, as HSV at full value.

    The type is drawn in this and the channel split then pulls it apart, so a
    saturated hue gives a fringe of its own complements rather than the plain
    red/cyan one. It is the main thing that separates one glitch style from
    another.
    """
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
        OpSpec("audio", "audiofileinCHOP", (-1800, 200),
               params={"file": cfg.track.instrumental or cfg.track.source or "",
                       "play": True, "repeat": False}),

        OpSpec("lyrics", "tableDAT", (-1800, -300), preserve=True),
        OpSpec("drums", "tableDAT", (-1800, -400), preserve=True),
        OpSpec("params", "textDAT", (-1800, -420), preserve=True),
        OpSpec("v7_script_callbacks", "textDAT", (-1800, -540), preserve=True),
        OpSpec("gl_words", "textDAT", (-1800, -660), preserve=True),

        # The map. Eight pixels wide on purpose: the sampled coordinate is
        # linear in x, so interpolating back up to frame width is exact.
        OpSpec("v7_script", "scriptTOP", (-1500, -400),
               params={"callbacks": "v7_script_callbacks", "resolutionw": MAP_W,
                       "resolutionh": s.height, "resmult": False,
                       "format": "rgba32float"}),

        OpSpec("gl_text", "textTOP", (-1500, -700), params={
            **frame, "font": s.font, "text": "", "dat": "gl_words",
            "alignx": "center", "aligny": "center", "wordwrap": True,
            # Points is the default and follows the display's DPI; pixels is the
            # only unit that means the same thing on two machines.
            "fontsizexunit": "pixels", "fontsizeyunit": "pixels",
            "positionunit": "pixels",
            "fontsizex": s.size, "fontsizey": s.size,
            "positiony": round((0.5 - s.line_y) * s.height, 2),
            "fontcolorr": round(ink[0], 4), "fontcolorg": round(ink[1], 4),
            "fontcolorb": round(ink[2], 4),
            "bgcolorr": 0.0, "bgcolorg": 0.0, "bgcolorb": 0.0, "bgalpha": 0.0}),

        # input1 is the picture, input2 the map.
        OpSpec("gl_remap", "remapTOP", (-1200, -700),
               params={**frame, "horzsource": "red", "vertsource": "green",
                       "extend": "zero", "resolutionsource": "input1"},
               inputs=["gl_text", "v7_script"]),

        # The channel split. `tx` is driven per frame by the field script so it
        # can answer the snare; what is set here is only the starting state.
        OpSpec("gl_plus", "transformTOP", (-1000, -850),
               params={**frame, "tunit": "pixels", "extend": "zero", "tx": 0.0},
               inputs=["gl_remap"]),
        OpSpec("gl_minus", "transformTOP", (-1000, -550),
               params={**frame, "tunit": "pixels", "extend": "zero", "tx": 0.0},
               inputs=["gl_remap"]),
        OpSpec("gl_split", "reorderTOP", (-800, -700), params={
            **frame,
            "outputred": "input1", "outputredchan": "red",
            "outputgreen": "input2", "outputgreenchan": "green",
            "outputblue": "input3", "outputbluechan": "blue",
            # Alpha from the unshifted copy: taking it from a shifted one makes
            # the type's silhouette lurch with the fringe.
            "outputalpha": "input2", "outputalphachan": "alpha"},
            inputs=["gl_plus", "gl_remap", "gl_minus"]),

        # The scanline mask rides in the map's blue channel; pull it out as a
        # mono image and multiply.
        OpSpec("gl_mask", "reorderTOP", (-1000, -300), params={
            **frame,
            "outputred": "input1", "outputredchan": "blue",
            "outputgreen": "input1", "outputgreenchan": "blue",
            "outputblue": "input1", "outputbluechan": "blue",
            "outputalpha": "input1", "outputalphachan": "one"},
            inputs=["v7_script"]),
        OpSpec("gl_lines", "compositeTOP", (-600, -700),
               params={**frame, "operand": "multiply"},
               inputs=["gl_split", "gl_mask"]),

        OpSpec("gl_lvl", "levelTOP", (-450, -700),
               params={**frame, "brightness1": lk.peak}, inputs=["gl_lines"]),

        OpSpec("gl_bloom", "blurTOP", (-450, -950),
               params={**frame, "size": lk.bloom}, inputs=["gl_lvl"]),
        OpSpec("gl_bloom_l", "levelTOP", (-300, -950),
               params={**frame, "brightness1": lk.glow}, inputs=["gl_bloom"]),
        OpSpec("gl_sum", "compositeTOP", (-300, -700),
               params={**frame, "operand": "add"},
               inputs=["gl_lvl", "gl_bloom_l"]),

        # The faint glow of a screen that is on but showing nothing. Scanlines
        # over pure black read as gaps; over a floor they read as a tube.
        OpSpec("gl_floor", "constantTOP", (-300, -1150), params={
            **frame,
            "colorr": round(ink[0] * lk.floor, 5),
            "colorg": round(ink[1] * lk.floor, 5),
            "colorb": round(ink[2] * lk.floor, 5), "alpha": 1.0}),
        OpSpec("gl_ground", "compositeTOP", (-200, -900),
               params={**frame, "operand": "add"},
               inputs=["gl_sum", "gl_floor"]),

        # nothing may exceed white; a Level TOP remaps rather than clamps
        OpSpec("gl_white", "constantTOP", (-300, -450), params=frame),
        OpSpec("gl_clamp", "compositeTOP", (-100, -700),
               params={**frame, "operand": "minimum"},
               inputs=["gl_ground", "gl_white"]),
        OpSpec("out", "nullTOP", (100, -700), params={"resmult": False},
               inputs=["gl_clamp"]),
    ]


def build(client, cfg, progress=None, container: str = ROOT,
          push: bool = True, calibrate: bool = True) -> dict:
    """Put the network into TouchDesigner.

    `calibrate` is accepted and ignored: the type here is one centred line, not
    glyphs on a lattice, so there are no metrics to solve for.
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
