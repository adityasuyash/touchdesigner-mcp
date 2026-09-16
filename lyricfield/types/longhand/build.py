"""Construct the longhand network.

One Text TOP per LETTER SIZE, each reading its own Specification DAT, over a
plate that is either the song's footage or a generated stand-in.

    v7_script (scriptTOP)   16px; writes every spec table and drives the plate
    plate                   moviefileinTOP, or the generated stand-in
    lh_fit (transformTOP)   cover-crop: scale to fill, centre, trim overflow
    lh_dim (levelTOP)       the plate brought down so white marker reads on it
    spec0..specN (tableDAT) one per letter size, the phrase arriving
    lh_text0..N (textTOP)   the lettering, sizes from `params.hand_sizes`
    wasspec0..N / lh_was0..N   the same again, for the phrase still leaving
    lh_now / lh_ghost       the two banks at their own brightnesses
    lh_ink (compositeTOP)   ... and the two of them together
    lh_over (compositeTOP)  the lettering OVER the plate
    ...bloomed, clamped -> out

Three things here have to be right:

  * The letters are summed with ADD, not `over`, and only then taken to `ink`.
    Each size draws a different subset of the same line, so between them the
    layers are transparent and never overlap -- but a composite `add` clamps at
    white on an 8-bit TOP, which is why the brightness is applied after the sum
    and not before it.
  * `over` is correct for putting the lettering on the plate, despite the note
    in CLAUDE.md that it does nothing over an opaque frame: the TEXT is the top
    layer and it carries alpha. It is the plate underneath that is opaque.
  * The cover-crop is an EXPRESSION, not a constant. A plate's dimensions are
    not knowable from Python at build time, so the scale is computed inside
    TouchDesigner from the operator's own width and height.
"""

from __future__ import annotations

from .._build import (OpSpec, ROOT, apply_exprs, check_types, create_ops,
                      drop_autocreated, wire_ops)
from .params import hand_sizes


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
    s, ln, g, lk = cfg.stage, cfg.line, cfg.ground, cfg.look
    frame = {"outputresolution": "custom", "resolutionw": s.width,
             "resolutionh": s.height, "resmult": False}
    sizes = hand_sizes(cfg.params if hasattr(cfg, "params") else cfg)
    n = len(sizes)
    plate = (getattr(cfg.track, "plate", "") or "").strip()

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
    ]

    # ---- the plate ---------------------------------------------------------
    if plate:
        specs += [
            # `textendright`, not `loop` -- a Movie File In has no `loop`;
            # looping is what it does past the end of the clip, and `cycle` is
            # the menu value. Asked TouchDesigner rather than inferred, which
            # is the rule here and has now caught three names in this file.
            OpSpec("plate", "moviefileinTOP", (-1800, -700),
                   params={"file": plate, "play": True,
                           "textendleft": "cycle", "textendright": "cycle"}),
            # `fillmode` "outside" IS cover-crop: scale until the image
            # covers the output and trim the overflow. This started as an
            # expression computing the ratio from `op('plate').width`, because
            # a plate's dimensions are not knowable from Python at build time
            # -- which was true and beside the point, since TouchDesigner does
            # not need to be told. Asking it what a Transform TOP has turned up
            # the parameter; the expression was two more things to get wrong.
            OpSpec("lh_fit", "transformTOP", (-1600, -700),
                   params={**frame, "extend": "zero", "fillmode": "outside"},
                   inputs=["plate"]),
        ]
        ground = "lh_fit"
    else:
        # No footage: a warm, soft, slowly drifting stand-in. Not pretending to
        # be film, but it gives the lettering something to sit on -- and it is
        # what every style preview records against, since a preview carries
        # nothing of the song that happens to be loaded.
        warm = _rgb(g.hue, g.sat)
        specs += [
            # `harmon` and `mono`, not `harmonics` and `monochrome`: asked
            # TouchDesigner rather than inferred, which is the rule here and
            # was written after a Level TOP turned out to have no `extendleft`.
            # And `tz` is an EXPRESSION -- assigning a string to a numeric
            # parameter errors rather than evaluating, so it goes through
            # `exprs`, which `apply_exprs` sets as `.expr` after creation.
            OpSpec("plate", "noiseTOP", (-1800, -700),
                   params={**frame, "type": "sparse", "period": 3.2,
                           "harmon": 2, "amp": 0.5, "offset": 0.5,
                           "mono": True},
                   exprs={"tz": "me.time.seconds/%g" % max(0.5, g.drift_secs)}),
            OpSpec("lh_soft", "blurTOP", (-1650, -700),
                   params={**frame, "size": g.blur}, inputs=["plate"]),
            # A Level TOP has no per-channel multiplier -- asked TouchDesigner,
            # and there is nothing like `redm` on it -- so the warmth comes
            # from a constant multiplied in, which is two operators and cannot
            # be got wrong.
            OpSpec("lh_warm", "constantTOP", (-1650, -900), params={
                **frame, "colorr": round(warm[0], 4),
                "colorg": round(warm[1], 4), "colorb": round(warm[2], 4)}),
            OpSpec("lh_tint", "compositeTOP", (-1500, -700),
                   params={**frame, "operand": "multiply"},
                   inputs=["lh_soft", "lh_warm"]),
            OpSpec("lh_fit", "levelTOP", (-1350, -700),
                   params={**frame, "brightness1": g.lift, "gamma1": 1.6},
                   inputs=["lh_tint"]),
        ]
        ground = "lh_fit"

    specs.append(
        # Brought down so white marker reads over it. A Level TOP rather than a
        # black card over the top: the reference darkens the picture, it does
        # not lay a scrim on it.
        OpSpec("lh_dim", "levelTOP", (-1200, -700),
               params={**frame, "opacity": round(1.0 - g.dim, 4)},
               inputs=[ground]))

    # ---- the lettering -----------------------------------------------------
    def text_par(px, spec):
        return {**frame, "font": s.font, "text": "", "specdat": spec,
                "alignx": "left",
                # Bottom, so a row's y IS its baseline and letters of different
                # sizes sit on one line instead of on their own centres. With
                # centre alignment a bigger letter rides up and the line reads
                # as bouncing rather than as drawn.
                "aligny": "bottom",
                # Points is the default and follows the display's DPI; pixels
                # is the only unit that means the same thing on two machines.
                "fontsizexunit": "pixels", "fontsizeyunit": "pixels",
                "positionunit": "pixels",
                "fontsizex": round(px, 2), "fontsizey": round(px, 2),
                "fontcolorr": 1.0, "fontcolorg": 1.0, "fontcolorb": 1.0,
                "bgcolorr": 0.0, "bgcolorg": 0.0, "bgcolorb": 0.0,
                "bgalpha": 0.0}

    def bank(stem, tops, y0):
        """One set of Text TOPs, summed. Two of these exist -- the phrase
        arriving and the one still leaving -- because a Text TOP has ONE colour
        for its whole Specification DAT and the two are at different
        opacities. The shape `monument` already uses for its ghost."""
        prev = None
        for i in range(n):
            y = y0 - i * 130
            specs.append(OpSpec("%s%d" % (stem, i), "tableDAT",
                                (-1800, y - 45), preserve=True))
            specs.append(OpSpec("%s%d" % (tops, i), "textTOP", (-1400, y),
                                params=text_par(sizes[i], "%s%d" % (stem, i))))
            cur = "%s%d" % (tops, i)
            if prev is None:
                prev = cur
            else:
                name = "%s_sum%d" % (tops, i)
                specs.append(OpSpec(name, "compositeTOP", (-1150, y),
                                    params={**frame, "operand": "add"},
                                    inputs=[prev, cur]))
                prev = name
        return prev

    now = bank("spec", "lh_text", -1100)
    was = bank("wasspec", "lh_was", -1700)

    specs += [
        # After the sum, never before: `add` clamps at white, so scaling the
        # layers first and adding second is what loses the brightness.
        OpSpec("lh_now", "levelTOP", (-950, -1100),
               params={**frame, "brightness1": lk.ink}, inputs=[now]),
        # The outgoing phrase, whose brightness the field script sets per frame
        # as it fades out. Starts dark: with nothing leaving, nothing shows.
        OpSpec("lh_ghost", "levelTOP", (-950, -1700),
               params={**frame, "brightness1": 0.0}, inputs=[was]),
        OpSpec("lh_ink", "compositeTOP", (-820, -1400),
               params={**frame, "operand": "add"},
               inputs=["lh_now", "lh_ghost"]),
        # The lettering over the plate. `over` is right here -- the text
        # carries alpha and the plate underneath is what is opaque.
        OpSpec("lh_over", "compositeTOP", (-700, -700),
               params={**frame, "operand": "over"},
               inputs=["lh_ink", "lh_dim"]),

        OpSpec("lh_bloom", "blurTOP", (-700, -400),
               params={**frame, "size": lk.bloom}, inputs=["lh_ink"]),
        OpSpec("lh_bloom_l", "levelTOP", (-550, -400),
               params={**frame, "brightness1": lk.glow}, inputs=["lh_bloom"]),
        OpSpec("lh_lit", "compositeTOP", (-400, -700),
               params={**frame, "operand": "add"},
               inputs=["lh_over", "lh_bloom_l"]),

        # The kick lift, from the 16px script, added across the whole frame.
        OpSpec("lh_ground", "levelTOP", (-700, -100),
               params={**frame, "fillmode": "fill"}, inputs=["v7_script"]),
        OpSpec("lh_sum", "compositeTOP", (-250, -700),
               params={**frame, "operand": "add"},
               inputs=["lh_lit", "lh_ground"]),

        # nothing may exceed white; a Level TOP remaps rather than clamps
        OpSpec("lh_white", "constantTOP", (-250, -950), params=frame),
        OpSpec("lh_clamp", "compositeTOP", (-100, -700),
               params={**frame, "operand": "minimum"},
               inputs=["lh_sum", "lh_white"]),
        OpSpec("out", "nullTOP", (100, -700), params={"resmult": False},
               inputs=["lh_clamp"]),
    ]
    return specs


def build(client, cfg, progress=None, container: str = ROOT,
          push: bool = True, calibrate: bool = True) -> dict:
    """Put the network into TouchDesigner.

    `calibrate` is accepted and ignored: the glyph metrics the grid renderers
    solve for do not arise here, because the Specification DAT places every
    letter at a pixel coordinate this script computed.
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
