"""The word layer, and what the beat does to it.

The renderer builds into `/project1/words` and everything after it is the beat
response: a fixed chain of operators whose parameters are driven each frame by
`fx_drive`, reading the drum table. `/project1/out` is the end of it, which is
what `render` records and what every check measures.

    words/out -> fx_in (select) -> fx_shake -> fx_zoom
              -> fx_r / fx_g / fx_b -> fx_split      (the fringe)
              -> fx_level -> fx_spark_add -> fx_bloom -> fx_add -> fx_clamp
                   ^              ^
                   |        fx_seed -> fx_burst -> fx_sparks   (the dust)
              fx_liftmap <- fx_drive's own pixels ARE the lift
                            fx_drive (16px script) sets the rest

Why a chain rather than code inside each renderer: there are eight word
renderers and the beat means the same thing to all of them. A preset is then a
set of numbers, and a new one costs a dict rather than eight edits that have to
stay in step.

This used to composite a second *renderer* under the words -- seven of them
existed for it. That premise is gone; see `beat.py`.

A Select TOP reaches into the container rather than a wire, because a TOP
inside a base COMP cannot be wired to one outside it and a COMP is not a valid
TOP input either. The `wire` tool reports success for the first and leaves the
input unconnected: measured, a live layer at 0.31 arriving as 0.0 with nothing
reporting a fault.
"""

from __future__ import annotations

from .types._build import (OpSpec, ROOT, apply_exprs, check_types, create_ops,
                           drop_autocreated, wire_ops)

WORDS = "words"


def container_for(cfg=None, which: str = WORDS) -> str:
    return f"{ROOT}/{which}"


def _frame(cfg) -> dict:
    """The output resolution, from whichever section this renderer keeps it in."""
    for name in ("stage", "grid", "frame"):
        sec = getattr(cfg.params, name, None)
        if sec is not None and hasattr(sec, "width"):
            return {"outputresolution": "custom",
                    "resolutionw": int(sec.width),
                    "resolutionh": int(sec.height),
                    "resmult": False}
    return {"outputresolution": "custom", "resolutionw": 720,
            "resolutionh": 1280, "resmult": False}


def network(cfg) -> list[OpSpec]:
    """The response chain. Always the same shape.

    Every operator is created whether or not its effect is switched on, and
    `fx_drive` sets the idle ones to their neutral values. A chain whose shape
    depends on the preset would have to be rebuilt every time one is picked,
    and rebuilding is what `verify` then has to reason about.
    """
    frame = _frame(cfg)
    split = bool(getattr(cfg.response.split, "on", False))

    specs = [
        OpSpec("drums", "tableDAT", (-1800, -900), preserve=True),
        OpSpec("fx_params", "textDAT", (-1800, -1020), preserve=True),
        OpSpec("fx_drive_callbacks", "textDAT", (-1800, -1140), preserve=True),
        # Not the picture: sixteen pixels nothing looks at, whose job is to set
        # the parameters of everything below. The `monument` pattern.
        OpSpec("fx_drive", "scriptTOP", (-1600, -1020),
               params={"callbacks": "fx_drive_callbacks", "resolutionw": 16,
                       "resolutionh": 16, "resmult": False,
                       "format": "rgba32float"}),

        OpSpec("fx_in", "selectTOP", (-1400, -400),
               params={**frame, "top": f"{WORDS}/out"}),
        # `zero` rather than `hold`: a shaken frame that smears its edge pixels
        # outward reads as a drag, not as a knock.
        OpSpec("fx_shake", "transformTOP", (-1200, -400),
               params={**frame, "tunit": "pixels", "extend": "zero",
                       "tx": 0.0, "ty": 0.0}, inputs=["fx_in"]),
        OpSpec("fx_zoom", "transformTOP", (-1000, -400),
               params={**frame, "extend": "zero", "sx": 1.0, "sy": 1.0},
               inputs=["fx_shake"]),
    ]

    if split:
        # Three copies, two of them displaced, recombined one channel each. A
        # Reorder TOP takes four inputs, so the whole fringe is one operator
        # plus two transforms.
        specs += [
            OpSpec("fx_r", "transformTOP", (-800, -600),
                   params={**frame, "tunit": "pixels", "extend": "zero",
                           "tx": 0.0}, inputs=["fx_zoom"]),
            OpSpec("fx_b", "transformTOP", (-800, -200),
                   params={**frame, "tunit": "pixels", "extend": "zero",
                           "tx": 0.0}, inputs=["fx_zoom"]),
            OpSpec("fx_split", "reorderTOP", (-600, -400), params={
                **frame,
                "outputred": "input1", "outputredchan": "red",
                "outputgreen": "input2", "outputgreenchan": "green",
                "outputblue": "input3", "outputbluechan": "blue",
                # Alpha from the undisplaced copy, or the type's silhouette
                # lurches with the fringe.
                "outputalpha": "input2", "outputalphachan": "alpha"},
                inputs=["fx_r", "fx_zoom", "fx_b"]),
        ]
        lit = "fx_split"
    else:
        lit = "fx_zoom"

    # ---- the burst: particles shed off the type ----------------------------
    # Two operators and a tap, always created whatever the preset is on. With
    # `burst.on` false the script writes zeros and the add below is free; a
    # chain whose SHAPE follows the preset is a chain `verify` has to reason
    # about, and `fx_split` is already as much of that as this file wants.
    #
    # `fx_burst` shares `fx_drive`'s callbacks DAT and tells itself apart by
    # `scriptOp.name`. Deliberately: a second pushed script is a second thing
    # that can be stale or never written, and a Script TOP whose callbacks are
    # empty draws black and reports nothing -- which is the silent success this
    # project has now been bitten by three times. One DAT also means
    # `sync.reset_drive_state` keeps working untouched, since both operators
    # are one module with one `S`.
    burst_w, burst_h = frame["resolutionw"] // 2, frame["resolutionh"] // 2
    seed_w, seed_h = frame["resolutionw"] // 4, frame["resolutionh"] // 4
    specs += [
        # What the particles come OFF: the type as it appears after the other
        # effects, at a quarter resolution. Measured in TouchDesigner, a
        # numpyArray readback costs 2.03ms a frame at 720x1280 and 0.17ms at
        # 180x320 -- and the emitters are jittered inside their cell anyway, so
        # the resolution buys nothing.
        OpSpec("fx_seed", "levelTOP", (-600, -100),
               params={"outputresolution": "custom", "resolutionw": seed_w,
                       "resolutionh": seed_h, "resmult": False,
                       "fillmode": "fill"}, inputs=[lit]),
        OpSpec("fx_burst", "scriptTOP", (-450, -100),
               params={"callbacks": "fx_drive_callbacks",
                       "outputresolution": "custom",
                       "resolutionw": burst_w, "resolutionh": burst_h,
                       "resmult": False, "format": "rgba32float"},
               inputs=["fx_seed"]),
        OpSpec("fx_sparks", "levelTOP", (-300, -100),
               params={**frame, "fillmode": "fill"}, inputs=["fx_burst"]),
    ]

    specs += [
        # The lift, as a SIGNAL rather than as a parameter write -- and that is
        # the whole reason these three operators exist.
        #
        # `fx_drive` had no outputs. A Script TOP with nothing downstream of it
        # is in nobody's cook chain, and `CookLevel.ALWAYS` governs how often an
        # operator cooks when something asks for it, not whether anything asks.
        # So the driver never ran in a render: measured on a real project with
        # `punch` picked, `fx_drive.outputs` was empty, its stats were None, and
        # `fx_zoom.sx` sat at exactly 1.0 while the params and the 963-row drum
        # table beside it were perfectly correct. One forced cook moved it.
        # Previews escaped it only because `capture_preview` force-cooks the
        # driver to ask it about the drums.
        #
        # A tap that changed nothing would have fixed the cook and invited the
        # next reader to delete it as dead weight. This is load-bearing: the
        # driver outputs the bloom's lift, `fx_liftmap` fills the frame with it,
        # and multiply-then-add is `word * (1 + lift)` -- exactly what the Level
        # TOP's `brightness1` used to do, with the driver in the path.
        OpSpec("fx_liftmap", "levelTOP", (-600, -650),
               params={**frame, "fillmode": "fill"}, inputs=["fx_drive"]),
        OpSpec("fx_gain", "compositeTOP", (-500, -650),
               params={**frame, "operand": "multiply"},
               inputs=[lit, "fx_liftmap"]),
        OpSpec("fx_level", "compositeTOP", (-400, -400),
               params={**frame, "operand": "add"}, inputs=[lit, "fx_gain"]),
        # The dust goes in BEFORE the bloom, so it glows with everything else
        # rather than sitting on top as a separate hard layer.
        OpSpec("fx_spark_add", "compositeTOP", (-300, -400),
               params={**frame, "operand": "add"},
               inputs=["fx_level", "fx_sparks"]),
        OpSpec("fx_bloom", "blurTOP", (-400, -150),
               params={**frame, "size": 0.0}, inputs=["fx_spark_add"]),
        # `add`, then clamped: the glow lifts the type rather than replacing it,
        # and a Level TOP remaps rather than clamps, so white is held by a
        # minimum against a constant.
        OpSpec("fx_add", "compositeTOP", (-200, -400),
               params={**frame, "operand": "add"},
               inputs=["fx_spark_add", "fx_bloom"]),
        OpSpec("fx_white", "constantTOP", (-200, -650), params=frame),
        OpSpec("fx_clamp", "compositeTOP", (0, -400),
               params={**frame, "operand": "minimum"},
               inputs=["fx_add", "fx_white"]),
        OpSpec("out", "nullTOP", (200, -400), params={"resmult": False},
               inputs=["fx_clamp"]),
    ]
    return specs


def build(client, cfg, progress=None) -> dict:
    """Build the renderer into its container, then the response chain."""
    say = progress or (lambda m: None)
    out: dict = {"words": "", "problems": []}

    box = container_for(cfg)
    say(f"building {cfg.video_type.name} into {box}")
    _make(client, box)
    r = cfg.video_type.build(client, cfg, progress=say, container=box,
                             push=False)
    out["words"] = box
    out["problems"] += list(r.get("problems") or [])

    say("wiring the beat response")
    specs = network(cfg)
    unknown = check_types(client, specs)
    if unknown:
        raise RuntimeError(f"unknown TD type constants: {unknown}")
    out["problems"] += create_ops(client, specs, progress=say, container=ROOT)
    out["problems"] += wire_ops(client, specs, progress=say, container=ROOT)
    out["problems"] += apply_exprs(client, specs, progress=say, container=ROOT)
    drop_autocreated(client, specs, progress=say, container=ROOT)
    return out


def verify(client, cfg) -> list[str]:
    return check_types(client, network(cfg))


def chain_missing(client, cfg) -> list[str]:
    """Which of the response chain's operators are not in the project.

    The chain's SHAPE depends on the preset -- `fx_r`/`fx_b`/`fx_split` exist
    only when the split is on -- so switching to a preset that needs them can
    never work by pushing parameters, however correct those parameters are.
    `network` is a pure function of the config, so the question is answerable
    by comparing names.
    """
    want = [s.name for s in network(cfg)]
    got = client.run(
        "def go():\n"
        f"    r = op({ROOT!r})\n"
        "    print(' '.join(sorted(c.name for c in r.children)) if r else '')\n"
        "go()").strip().split()
    return [n for n in want if n not in set(got)]


def rebuild_chain(client, cfg, progress=None) -> list[str]:
    """Put the response chain back, without touching the renderer.

    Cheaper than a full provision and enough for a preset whose shape differs:
    the DATs that hold content are `preserve=True`, so re-creating is safe.
    """
    say = progress or (lambda m: None)
    specs = network(cfg)
    out = create_ops(client, specs, progress=say, container=ROOT)
    out += wire_ops(client, specs, progress=say, container=ROOT)
    out += apply_exprs(client, specs, progress=say, container=ROOT)
    drop_autocreated(client, specs, progress=say, container=ROOT)
    return out


def _make(client, box: str) -> None:
    """An empty container to build into, replacing whatever was there."""
    parent, name = box.rsplit("/", 1)
    client.run(
        "def go():\n"
        f"    r = op({parent!r})\n"
        f"    e = r.op({name!r})\n"
        "    if e: e.destroy()\n"
        f"    b = r.create(baseCOMP, {name!r})\n"
        "    return 'made'\n"
        "go()")


def drive_source() -> str:
    """The `fx_drive` script, with the shared prelude in front of it.

    Same shape as `VideoType.field_source`, and for the same reason: it is
    pushed as one DAT and cannot import a sibling, so `_read_drums` and
    `_read_params` have to travel with it.
    """
    from pathlib import Path

    here = Path(__file__).parent
    prelude = (here / "types" / "_prelude.py").read_text(encoding="utf-8")
    body = (here / "fx_drive.py").read_text(encoding="utf-8")
    return prelude + "\n\n" + body


def drive_params(cfg) -> dict:
    """The flat dict `fx_drive` reads, named the way its DEFAULTS are."""
    out = {}
    for section in ("zoom", "bloom", "shake", "split", "burst"):
        sec = getattr(cfg.response, section)
        for k, v in vars(sec).items():
            out[f"{section}_{k}"] = v
    frame = _frame(cfg)
    out["width"] = frame["resolutionw"]
    out["height"] = frame["resolutionh"]
    out["offset"] = float(getattr(cfg.params, "cueing", None)
                          and getattr(cfg.params.cueing, "offset", 0.0) or 0.0)
    return out
