"""Construct the spectrum network.

Short, because the Script TOP is the picture. The one thing here that no other
renderer needs is the `bands` table: every other type answers onsets from
`drums`, and this one draws the measurement itself.

    bands (tableDAT)        the measured spectrum, pushed by sync
    v7_script (scriptTOP)   the bars, at `scale` of the frame
    sp_up (levelTOP)        up to full size
    ...floor, bloom, glow, clamp -> out

The scale-up is `nearest` on purpose. A bar's edge is the whole point of a bar;
interpolating it up turns the chart into a soft heightmap.
"""

from __future__ import annotations

from .._build import (OpSpec, ROOT, apply_exprs, check_types, create_ops,
                      drop_autocreated, wire_ops)


def _rgb(h: float, sat: float) -> tuple[float, float, float]:
    """The ground's colour: the low end of the bars' own hue ramp."""
    h = (h % 1.0) * 6.0
    i = int(h)
    f = h - i
    p, q, t = 0.0, 1.0 - f, f
    r, g, b = ((1.0, t, p), (q, 1.0, p), (p, 1.0, t),
               (p, q, 1.0), (t, p, 1.0), (1.0, p, q))[i % 6]
    return ((1.0 - sat) + sat * r, (1.0 - sat) + sat * g,
            (1.0 - sat) + sat * b)


def network(cfg) -> list[OpSpec]:
    f, lk = cfg.frame, cfg.look
    frame = {"outputresolution": "custom", "resolutionw": f.width,
             "resolutionh": f.height, "resmult": False}
    fw = max(8, int(f.width * f.scale))
    fh = max(8, int(f.height * f.scale))
    ink = _rgb(lk.hue, lk.sat)

    return [
        OpSpec("audio", "audiofileinCHOP", (-1600, 200),
               params={"file": cfg.track.instrumental or cfg.track.source or "",
                       "play": True, "repeat": False}),

        OpSpec("drums", "tableDAT", (-1600, -400), preserve=True),
        # The one input no other renderer has.
        OpSpec("bands", "tableDAT", (-1600, -460), preserve=True),
        OpSpec("params", "textDAT", (-1600, -420), preserve=True),
        OpSpec("v7_script_callbacks", "textDAT", (-1600, -540), preserve=True),

        OpSpec("v7_script", "scriptTOP", (-1200, -400),
               params={"callbacks": "v7_script_callbacks", "resolutionw": fw,
                       "resolutionh": fh, "resmult": False,
                       "format": "rgba32float"}),
        OpSpec("sp_up", "levelTOP", (-1000, -400),
               params={**frame, "fillmode": "fill",
                       "inputfiltertype": "nearest",
                       "brightness1": lk.peak}, inputs=["v7_script"]),

        OpSpec("sp_bloom", "blurTOP", (-800, -150),
               params={**frame, "size": lk.bloom}, inputs=["sp_up"]),
        OpSpec("sp_bloom_l", "levelTOP", (-600, -150),
               params={**frame, "brightness1": lk.glow}, inputs=["sp_bloom"]),
        OpSpec("sp_sum", "compositeTOP", (-400, -400),
               params={**frame, "operand": "add"},
               inputs=["sp_up", "sp_bloom_l"]),

        OpSpec("sp_floor", "constantTOP", (-400, -900), params={
            **frame,
            "colorr": round(ink[0] * lk.floor, 5),
            "colorg": round(ink[1] * lk.floor, 5),
            "colorb": round(ink[2] * lk.floor, 5), "alpha": 1.0}),
        OpSpec("sp_ground", "compositeTOP", (-300, -650),
               params={**frame, "operand": "add"},
               inputs=["sp_sum", "sp_floor"]),

        # nothing may exceed white; a Level TOP remaps rather than clamps
        OpSpec("sp_white", "constantTOP", (-300, -1100), params=frame),
        OpSpec("sp_clamp", "compositeTOP", (-100, -400),
               params={**frame, "operand": "minimum"},
               inputs=["sp_ground", "sp_white"]),
        OpSpec("out", "nullTOP", (100, -400), params={"resmult": False},
               inputs=["sp_clamp"]),
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
