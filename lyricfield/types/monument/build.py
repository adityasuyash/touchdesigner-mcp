"""Construct the monument network.

Its own graph, built with the shared engine. Nothing is imported from
`lyric_grid.build` -- that import is what made two renderers draw the same
character field, and the whole purpose of this type is to draw something else.

The picture is two Text TOPs and a ground:

    word / word_prev (textDAT)  the current word and the one before it
    v7_script (scriptTOP)       the ground, and the driver: it writes those
                                DATs and sets the transforms every frame
    mon_now / mon_was (textTOP) the type itself, at whatever size fits
    ...transform, level, bloom, glow, clamp -> out

There is no Feedback TOP. The afterimage is the previous word drawn explicitly
as a second, dimmer, larger layer, because feedback only renders identically
when frame one is clean and a take that cannot be re-rendered is not a take.
"""

from __future__ import annotations

from .._build import (OpSpec, ROOT, apply_exprs, check_types, create_ops,
                      drop_autocreated, wire_ops)


def network(cfg) -> list[OpSpec]:
    """The whole monument network, generated from this song's config."""
    s, w, lk = cfg.stage, cfg.word, cfg.look

    frame = {"outputresolution": "custom", "resolutionw": s.width,
             "resolutionh": s.height, "resmult": False}
    # The field script sets size and position per word, so what is baked here
    # is only what does not change: the face, and that it is centred.
    # White type on a transparent ground; the ground is a separate branch, so
    # the Text TOPs must not paint their own. `bordera`/`borderb` do not exist
    # -- the real names are `borderar`, `borderag` and so on -- and there is no
    # border wanted here anyway.
    text = {**frame, "font": s.font, "alignx": "center", "aligny": "center",
            # Empty, or the Text TOP draws its own inline string and ignores
            # the DAT entirely -- it ships holding the word "derivative", which
            # is what this renderer drew until it was looked at.
            "text": "",
            # PIXELS. The parameter defaults to points, so every size this
            # renderer computes from the frame width would be scaled by the
            # display's DPI -- the same class of bug that once made a grid's
            # row pitch depend on the monitor it was built on.
            "fontsizexunit": "pixels", "fontsizeyunit": "pixels",
            "fontsizex": 120.0, "fontsizey": 120.0,
            "fontcolorr": 1.0, "fontcolorg": 1.0, "fontcolorb": 1.0,
            "bgcolorr": 0.0, "bgcolorg": 0.0, "bgcolorb": 0.0,
            "bgalpha": 0.0}

    return [
        # ---- audio, for the glow's low-band breath ----
        OpSpec("audio", "audiofileinCHOP", (-1600, 200),
               params={"file": cfg.track.instrumental or cfg.track.source or "",
                       "play": True, "repeat": False}),

        # ---- data the field script reads and writes ----
        OpSpec("lyrics", "tableDAT", (-1600, -300), preserve=True),
        OpSpec("drums", "tableDAT", (-1600, -400), preserve=True),
        OpSpec("params", "textDAT", (-1600, -420), preserve=True),
        OpSpec("v7_script_callbacks", "textDAT", (-1600, -540), preserve=True),
        # One word each. Written every frame by the field script.
        OpSpec("word", "textDAT", (-1600, -660), preserve=True),
        OpSpec("word_prev", "textDAT", (-1600, -780), preserve=True),

        # ---- the driver ----
        # Small: this Script TOP is not the picture, it is the ground and the
        # hand that moves everything else. Sixteen pixels of flat colour cost
        # nothing and upscale to a clean wash.
        OpSpec("v7_script", "scriptTOP", (-1200, -400),
               params={"callbacks": "v7_script_callbacks", "resolutionw": 16,
                       "resolutionh": 16, "resmult": False,
                       "format": "rgba32float"}),
        # `fill` stretches the sixteen-pixel ground across the whole frame.
        # A Level TOP has no extend parameters -- that vocabulary belongs to
        # other operators, and TouchDesigner said so rather than guessing.
        OpSpec("mon_ground", "levelTOP", (-1000, -400),
               params={**frame, "fillmode": "fill"},
               inputs=["v7_script"]),

        # ---- the type ----
        OpSpec("mon_was", "textTOP", (-1000, -700),
               params={**text, "dat": "word_prev"}),
        OpSpec("mon_now", "textTOP", (-1000, -100),
               params={**text, "dat": "word", "bold": True}),
        # The field script drives these two every frame: `scale` for the punch
        # and the ghost's size, `ty` for the drift.
        OpSpec("mon_was_x", "transformTOP", (-800, -700),
               params={**frame}, inputs=["mon_was"]),
        OpSpec("mon_now_x", "transformTOP", (-800, -100),
               params={**frame}, inputs=["mon_now"]),
        # Blurred, and that is not decoration. Left sharp, a two-letter ghost
        # behind a three-letter word simply reads as more letters -- "TO"
        # behind "SAY" came out as "STAY" the first time this was rendered.
        # Softening it is what makes it read as the word before rather than as
        # part of this one.
        OpSpec("mon_was_b", "blurTOP", (-700, -700),
               params={**frame, "size": lk.bloom * 1.6}, inputs=["mon_was_x"]),
        OpSpec("mon_was_l", "levelTOP", (-600, -700),
               params={**frame, "brightness1": w.ghost}, inputs=["mon_was_b"]),
        OpSpec("mon_now_l", "levelTOP", (-600, -100),
               params={**frame, "brightness1": lk.peak}, inputs=["mon_now_x"]),

        # ---- composite ----
        OpSpec("mon_type", "compositeTOP", (-400, -400),
               params={**frame, "operand": "add"},
               inputs=["mon_was_l", "mon_now_l"]),
        OpSpec("mon_sum1", "compositeTOP", (-200, -400),
               params={**frame, "operand": "add"},
               inputs=["mon_ground", "mon_type"]),

        # tight bloom on the type alone, so the ground does not smear
        OpSpec("mon_bloom", "blurTOP", (-400, -150),
               params={**frame, "size": lk.bloom}, inputs=["mon_now_l"]),
        OpSpec("mon_bloom_l", "levelTOP", (-200, -150),
               params={**frame, "brightness1": lk.glow}, inputs=["mon_bloom"]),
        OpSpec("mon_sum2", "compositeTOP", (0, -400),
               params={**frame, "operand": "maximum"},
               inputs=["mon_sum1", "mon_bloom_l"]),

        # nothing may exceed white; a Level TOP remaps rather than clamps, so
        # the ceiling is a minimum against a white constant
        OpSpec("mon_white", "constantTOP", (0, -650), params=frame),
        OpSpec("mon_clamp", "compositeTOP", (200, -400),
               params={**frame, "operand": "minimum"},
               inputs=["mon_sum2", "mon_white"]),
        OpSpec("out", "nullTOP", (400, -400), params={"resmult": False},
               inputs=["mon_clamp"]),
    ]


def build(client, cfg, progress=None, container: str = ROOT,
          push: bool = True, calibrate: bool = True) -> dict:
    """Put the network into TouchDesigner, from an empty project if need be.

    `calibrate` is accepted and ignored: it exists because the grid types must
    solve their font metrics by measurement before anything lines up with the
    frame. This renderer centres one word, so there is nothing to solve.
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
    """What the live network has that the spec does not, and the reverse.

    A discrepancy makes `provision` rebuild. Kept narrow deliberately: the
    field script drives `mon_now_x`/`mon_was_x` parameters every frame, so
    comparing those values against the spec would report a difference on every
    single frame and rebuild forever.
    """
    specs = network(cfg)
    return check_types(client, specs)
