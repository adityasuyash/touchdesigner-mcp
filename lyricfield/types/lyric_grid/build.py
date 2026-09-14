"""Construct the lyric_grid network inside TouchDesigner, from an empty project.

This is what keeps the repo the source of truth. Before it existed, a new song
was provisioned by saving whatever TouchDesigner happened to have open, which
works for exactly one video type and puts the only copy of the network inside a
binary that cannot be diffed, reviewed or recovered.

The network is declared as data (`network(cfg)`) and the same declaration drives
both `build()` and `verify()`, so the builder and the checker cannot drift apart.
Every constant is generated from `cfg.params`: the glow and bloom values used to
sit as literals inside TouchDesigner expressions, where they quietly fell out of
step with the config that claimed to own them.

The text geometry is the one thing not derived but *measured* -- see
`calibrate_text`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ROOT = "/project1"
SCRIPT_TOP_NAME = ROOT + "/v7_script"
TEXT_TOPS = (ROOT + "/v7_text_dim", ROOT + "/v7_text_lit")

# The audioAnalysis component ships with TouchDesigner. Its .tox is a palette
# wrapper -- `help`, `icon`, and the real 136-operator container nested inside --
# so it is loaded and then unwrapped rather than used directly.
PALETTE_RELPATHS = (
    "Contents/Resources/tfs/Samples/Palette/Tools/audioAnalysis.tox",   # macOS
    "Samples/Palette/Tools/audioAnalysis.tox",                          # Windows/Linux
    "Config/Palette/Tools/audioAnalysis.tox",
)
ANALYSIS_COMP = "aa"
ANALYSIS_OUT = "aa/out1"

# Operators the build must never touch: the MCP server it is talking through,
# and the scratch operators the render tool creates.
PROTECTED = ("td_mcp_server", "_mcp_movieout", "_mcp_audioout")


@dataclass
class OpSpec:
    name: str
    type: str                                   # TD type constant, e.g. 'blurTOP'
    pos: tuple[int, int]
    params: dict = field(default_factory=dict)  # constant values
    exprs: dict = field(default_factory=dict)   # expression strings
    inputs: list[str] = field(default_factory=list)   # sibling names, in order
    # Create only if absent, never replace. The `create` tool destroys a
    # same-named operator first, so without this a rebuild would silently wipe
    # the cue table -- the one thing in the network that may exist nowhere else.
    preserve: bool = False


def network(cfg) -> list[OpSpec]:
    """The whole lyric_grid network, generated from this song's config."""
    g, lk, an, tr = cfg.grid, cfg.look, cfg.analysis, cfg.track

    frame = {"outputresolution": "custom", "resolutionw": g.width,
             "resolutionh": g.height, "resmult": False}
    # The field is a 24x24 image blown up to full frame. Without nearest-neighbour
    # sampling every letter turns to mush.
    nearest = {**frame, "inputfiltertype": "nearest", "filtertype": "nearest"}
    text = {
        **frame, "format": "rgba16float", "text": "",
        "font": g.font,
        "fontsizex": g.font_px, "fontsizexunit": "pixels",
        "fontsizey": g.font_px * g.glyph_aspect, "fontsizeyunit": "pixels",
        "alignx": "left", "aligny": "top", "bgalpha": 1.0,
    }

    def audio(path, clock="me.time.rate"):
        return dict(params={"file": path, "playmode": "locked", "mono": True},
                    exprs={"index": f"me.time.frame / {clock}",
                           "timecodeop": "tdu.Timecode()"})

    glow_size = f"{lk.glow_radius:g} + {lk.glow_radius_lfo:g}*op('v9_lfo')[0]"
    glow_bright = (
        f"{lk.glow_base:g} + {lk.glow_lfo:g}*op('v9_lfo')[0]"
        f" + {lk.glow_low:g}*min(1.0, abs(op('v8_low_lag')[0])/{lk.glow_low_knee:g})"
    )

    return [
        # ---- audio in ----
        # `audio` follows root time because the field script reads
        # root.time.seconds; the crossfade pair follow the local timeline. That
        # split is inherited from the hand-built network and is left alone
        # deliberately -- this project has a /local/time, so the two can diverge.
        OpSpec("audio", "audiofileinCHOP", (-1600, 400),
               **audio(tr.source, clock="root.time.rate")),
        OpSpec("cf_vocal", "audiofileinCHOP", (-1600, 250), **audio(tr.vocals)),
        OpSpec("cf_instr", "audiofileinCHOP", (-1600, 100), **audio(tr.instrumental)),
        OpSpec("cf_mix", "mathCHOP", (-1400, 175), params={"chopop": "add"},
               inputs=["cf_vocal", "cf_instr"]),

        # ---- beat analysis (aa is loaded from the palette, not created here) ----
        OpSpec("v6_aa", "nullCHOP", (-1000, 100), inputs=[ANALYSIS_OUT]),
        OpSpec("v8_low", "selectCHOP", (-800, 100), params={"channames": "low"},
               inputs=["v6_aa"]),
        OpSpec("v8_low_lag", "lagCHOP", (-600, 100),
               params={"lag1": an.low_lag_up, "lag2": an.low_lag_dn},
               inputs=["v8_low"]),
        OpSpec("v9_lfo", "lfoCHOP", (-600, 250),
               params={"frequency": lk.glow_lfo_hz},
               exprs={"rate": "me.time.rate"}),

        # ---- data the field script reads and writes ----
        # Content, not structure: sync writes these and a cue table may exist
        # only here (sync.pull_cues exists to recover exactly that case).
        OpSpec("lyrics", "tableDAT", (-1600, -300), preserve=True),
        # Preserved for the same reason the cue table is: it is pushed in from
        # the repo and a rebuild must not wipe what was measured.
        OpSpec("drums", "tableDAT", (-1600, -400), preserve=True),
        OpSpec("params", "textDAT", (-1600, -420), preserve=True),
        OpSpec("v7_script_callbacks", "textDAT", (-1600, -540), preserve=True),
        OpSpec("v7_chars_dim", "textDAT", (-1600, -660), preserve=True),
        OpSpec("v7_chars_lit", "textDAT", (-1600, -780), preserve=True),

        # ---- the field itself ----
        OpSpec("v7_script", "scriptTOP", (-1200, -400),
               params={"callbacks": "v7_script_callbacks", "resolutionw": g.cols,
                       "resolutionh": g.vrows, "resmult": False,
                       "format": "rgba32float"}),

        # RGB carries the dim layer's colour, ALPHA the lit layer's weight
        OpSpec("v7_bright", "levelTOP", (-1000, -500), params=nearest,
               inputs=["v7_script"]),
        OpSpec("v8_lit_w", "reorderTOP", (-1000, -300),
               params={"outputredchan": "alpha", "outputgreenchan": "alpha",
                       "outputbluechan": "alpha", "outputalphachan": "one"},
               inputs=["v7_script"]),
        OpSpec("v8_bright_lit", "levelTOP", (-800, -300), params=nearest,
               inputs=["v8_lit_w"]),

        OpSpec("v7_text_dim", "textTOP", (-1000, -700), params=
               {**text, "dat": "v7_chars_dim"}),
        OpSpec("v7_text_lit", "textTOP", (-1000, -100), params=
               {**text, "dat": "v7_chars_lit", "bold": True}),

        OpSpec("v7_dim", "compositeTOP", (-600, -600), params={"resmult": False},
               inputs=["v7_text_dim", "v7_bright"]),
        OpSpec("v8_lit", "compositeTOP", (-600, -200), params={"resmult": False},
               inputs=["v7_text_lit", "v8_bright_lit"]),

        OpSpec("v7_sum1", "compositeTOP", (-400, -400),
               params={"operand": "add", "resmult": False},
               inputs=["v7_dim", "v8_lit"]),

        # tight bloom on lit words only
        OpSpec("v7_bloom", "blurTOP", (-400, -150),
               params={"size": lk.bloom_size, "resmult": False},
               inputs=["v8_lit"]),
        OpSpec("v7_bloom_lvl", "levelTOP", (-200, -150),
               params={"brightness1": lk.bloom_bright, "resmult": False},
               inputs=["v7_bloom"]),
        OpSpec("v7_sum2", "compositeTOP", (-200, -400),
               params={"operand": "maximum", "resmult": False},
               inputs=["v7_sum1", "v7_bloom_lvl"]),

        # wide glow over the whole field, breathing on the LFO and the low band
        OpSpec("v9_glow_blur", "blurTOP", (-400, -650), params={"resmult": False},
               exprs={"size": glow_size}, inputs=["v7_sum1"]),
        OpSpec("v9_glow_lvl", "levelTOP", (-200, -650), params={"resmult": False},
               exprs={"brightness1": glow_bright}, inputs=["v9_glow_blur"]),
        OpSpec("v9_sum3", "compositeTOP", (0, -400),
               params={"operand": "add", "resmult": False},
               inputs=["v7_sum2", "v9_glow_lvl"]),

        # nothing may exceed white; a Level TOP remaps rather than clamps, so the
        # ceiling is a minimum against a white constant
        OpSpec("v9_white", "constantTOP", (0, -650), params=frame),
        OpSpec("v9_clamp", "compositeTOP", (200, -400),
               params={"operand": "minimum", "resmult": False},
               inputs=["v9_sum3", "v9_white"]),
        OpSpec("out", "nullTOP", (400, -400), params={"resmult": False},
               inputs=["v9_clamp"]),
    ]


# --------------------------------------------------------------------- helpers

def _py(v) -> str:
    return repr(v)


def _run(client, body: str, timeout: float | None = None) -> str:
    """Run a function body inside TD and return what it printed.

    Everything is wrapped in `main()` because the server's exec scope gives
    module-level names no visibility inside nested defs.
    """
    return client.run("def main():\n" + body + "\nprint(main())", timeout=timeout)


def load_analysis_component(client, cfg, progress=None, container: str = ROOT) -> str:
    """Load the stock audioAnalysis palette component and wire its gates.

    The .tox is a palette wrapper containing `help`, `icon` and the real
    container, so it is loaded, unwrapped by copying the inner component out
    under our own name, and the wrapper discarded.
    """
    say = progress or (lambda m: None)
    an = cfg.analysis
    # Scaled to this master's measured loudness. Pushed raw, these gates are one
    # song's numbers: a quiet track crosses none of them and gets no beat
    # response at all, for its whole length, with nothing reporting it.
    gates = an.scaled(getattr(cfg.track, "level", 0.0))
    say(f"loading the audioAnalysis palette component "
        f"(gates x{gates['factor']} for this master)")
    pars = {
        "Kickthresh": gates["kick_thresh"], "Snarethresh": gates["snare_thresh"],
        "Rythmthresh": gates["rythm_thresh"], "Lowthresh": gates["low_thresh"],
        "Lowsmooth": gates["low_smooth"], "Highgain": gates["high_gain"],
        "Lowactive": True, "Midactive": True, "Highactive": True,
        "Kickactive": True, "Snareactive": True, "Rythmactive": True,
        "Ssdactive": True,
    }
    out = _run(client, f"""
    import os
    root = op({container!r})
    path = None
    for rel in {PALETTE_RELPATHS!r}:
        p = os.path.join(app.installFolder, rel)
        if os.path.isfile(p):
            path = p
            break
    if path is None:
        return 'ERROR: audioAnalysis.tox not found under ' + app.installFolder
    for junk in ('audioAnalysis', {ANALYSIS_COMP!r}):
        k = root.op(junk)
        if k is not None:
            k.destroy()
    wrapper = root.loadTox(path)
    inner = wrapper.op('audioAnalysis') or wrapper
    aa = root.copy(inner, name={ANALYSIS_COMP!r})
    aa.nodeX, aa.nodeY = -1200, 100
    if wrapper is not inner:
        wrapper.destroy()
    for k, v in {pars!r}.items():
        if hasattr(aa.par, k):
            setattr(aa.par, k, v)
    src = root.op('cf_instr')
    if src is not None:
        aa.inputConnectors[0].connect(src)
    o = aa.op('out1')
    return 'ok %d children, out1=%s' % (len(aa.children), o is not None)
""", timeout=180.0)
    if "ERROR" in out:
        raise RuntimeError(out.strip())
    say(out.strip())
    return out.strip()


def create_ops(client, specs, progress=None, container: str = ROOT) -> list[str]:
    """Create every operator with its constant parameters, no wiring yet.

    Expressions and connections are applied afterwards, once every operator they
    reference exists -- otherwise the server evaluates a reference to a missing
    operator and reports it as a failure.
    """
    say = progress or (lambda m: None)
    problems: list[str] = []
    for s in specs:
        if s.preserve:
            made = _run(client, f"""
    parent = op({container!r})
    o = parent.op({s.name!r})
    if o is not None:
        return 'kept'
    o = parent.create({s.type}, {s.name!r})
    o.nodeX, o.nodeY = {s.pos[0]}, {s.pos[1]}
    return 'created'
""").strip()
            say(f"{s.name}: {made}")
            continue
        say(f"creating {s.name} ({s.type})")
        res = client.call("create", type=s.type, name=s.name, parent=container,
                          nodeX=s.pos[0], nodeY=s.pos[1], params=s.params)
        if '"errors"' in res:
            problems.append(f"{s.name}: {res}")
    return problems


def drop_autocreated(client, specs, progress=None, container: str = ROOT) -> list[str]:
    """Remove the callbacks DAT a Script TOP makes for itself.

    Creating a scriptTOP named `v7_script` makes a `v7_script_callbacks` DAT
    alongside it. We create that DAT ourselves first (it is preserved content,
    holding the field script), so TouchDesigner's copy lands as
    `v7_script_callbacks1` and is left orphaned in the network.
    """
    say = progress or (lambda m: None)
    # Only the Script TOP's own callbacks DAT, by exact name. An earlier version
    # matched any spec name plus digits and destroyed `v6_aa2` -- a pre-existing
    # operator that merely looked like "v6_aa" with a suffix. A builder must
    # never delete something it did not create.
    scripts = [sp.name for sp in specs if sp.type == "scriptTOP"]
    suspects = [f"{n}_callbacks{i}" for n in scripts for i in range(1, 10)]
    out = _run(client, f"""
    parent = op({container!r})
    dropped = []
    for n in {suspects!r}:
        c = parent.op(n)
        if c is not None:
            dropped.append(n)
            c.destroy()
    return repr(dropped)
""")
    try:
        dropped = eval(out.strip())
    except Exception:
        return []
    if dropped:
        say(f"removed auto-created duplicates: {dropped}")
    return dropped


def wire_ops(client, specs, progress=None, container: str = ROOT) -> list[str]:
    say = progress or (lambda m: None)
    conns = []
    for s in specs:
        for i, src in enumerate(s.inputs):
            conns.append({"from": f"{container}/{src}", "to": f"{container}/{s.name}",
                          "to_input": i})
    if not conns:
        return []
    say(f"wiring {len(conns)} connections")
    res = client.call("wire", connections=conns)
    return [res] if '"errors"' in res else []


def apply_exprs(client, specs, progress=None, container: str = ROOT) -> list[str]:
    say = progress or (lambda m: None)
    problems = []
    for s in specs:
        if not s.exprs:
            continue
        say(f"expressions on {s.name}")
        res = client.call("set", path=f"{container}/{s.name}", exprs=s.exprs)
        if '"errors"' in res:
            problems.append(f"{s.name}: {res}")
    return problems


# ----------------------------------------------------------------- calibration

def _glyph_centre(client, cfg, cell, tracking, spacing, posx=0.0, posy=0.0):
    """Write one glyph at `cell` and return where its pixels actually land.

    Returns (cx, cy) in pixels from the top-left of the frame, or None if the
    glyph fell outside the image entirely.
    """
    g = cfg.grid
    r, c = cell
    rows = [[" "] * g.cols for _ in range(g.vrows)]
    rows[r][c] = "#"
    client.write(f"{ROOT}/v7_chars_dim", "\n".join("".join(x) for x in rows))
    client.call("set", path=f"{ROOT}/v7_text_dim",
                params={"trackingx": tracking, "linespacing": spacing,
                        "positionx": posx, "positiony": posy})
    out = _run(client, f"""
    import numpy as np
    t = op({ROOT + '/v7_text_dim'!r})
    t.cook(force=True)
    a = t.numpyArray()
    lum = a[:, :, :3].max(axis=2)
    ys, xs = np.nonzero(lum > 0.25)
    if not len(xs):
        return 'NONE'
    h = lum.shape[0]
    # numpyArray comes back bottom-up; convert to top-down pixel coordinates
    return repr((float(xs.mean()), float(h - 1 - ys.mean())))
""")
    out = out.strip()
    if out == "NONE" or not out:
        return None
    try:
        return eval(out)
    except Exception:
        return None


def _text_geometry(client, container: str = ROOT) -> dict | None:
    """The four glyph-placement numbers as they stand, so they can be put back."""
    out = _run(client, f"""
    t = op({TEXT_TOPS[0]!r})
    if t is None:
        return 'NONE'
    return '%r %r %r %r' % (t.par.trackingx.eval(), t.par.linespacing.eval(),
                            t.par.positionx.eval(), t.par.positiony.eval())
""")
    if not out or out.strip() == "NONE":
        return None
    try:
        tr, sp, px, py = (float(v) for v in out.split())
    except ValueError:
        return None
    return {"tracking": tr, "spacing": sp, "posx": px, "posy": py}


def apply_text_geometry(client, tracking: float, spacing: float,
                        posx: float, posy: float) -> None:
    """Put the solved geometry on BOTH text layers.

    The lit layer used to be left at whatever it was created with, because
    calibration only ever touched the dim layer it probed through -- so the bold
    words sat on a different grid from the dim ones.
    """
    for path in TEXT_TOPS:
        client.call("set", path=path,
                    params={"trackingx": tracking, "linespacing": spacing,
                            "positionx": posx, "positiony": posy})


def _give_up(client, before: dict | None, error: str) -> dict:
    """Abandon the solve without leaving probe values on the network."""
    if before:
        apply_text_geometry(client, **before)
    _run(client, f"""
    sc = op({SCRIPT_TOP_NAME!r})
    if sc is not None:
        sc.bypass = False
    return 'ok'
""")
    return {"ok": False, "error": error}


def calibrate_text(client, cfg, progress=None) -> dict:
    """Solve the Text TOP geometry by measurement instead of by algebra.

    The four numbers that place glyphs on the grid -- positionx, positiony,
    trackingx, linespacing -- are font metrics. For 24x24 at 720x1280 in 50px
    Courier New they happen to be -1/44, 0.625, -10.5625 and 13.2899, and none of
    those generalise: `grid.font` is a parameter, so the next font moves all four.

    So measure. Two probes give the natural advance on each axis; a third, with
    tracking changed by a known amount, gives tracking's units, which are not
    documented per font. Then solve for the values that put each cell's glyph at
    its cell centre, and confirm with a final probe.

    Returns the solved parameters and the residual error in pixels. A residual
    above about a third of a cell means the solve did not converge and the
    caller should not trust the layout.
    """
    say = progress or (lambda m: None)
    g = cfg.grid
    cell_w, cell_h = g.width / g.cols, g.height / g.vrows
    probe = lambda cell, t, sp, px=0.0, py=0.0: _glyph_centre(
        client, cfg, cell, t, sp, px, py)

    # Probing writes directly into the character DAT and reads the Text TOP
    # back, so the Script TOP must not be rewriting that DAT underneath it --
    # it cooks ALWAYS. Bypass it here rather than trusting the caller to have
    # done it, and put the geometry back if the solve gives up partway: a
    # half-finished calibration used to leave the Text TOP holding a *probe*
    # value (trackingx 0.1, linespacing 0), which silently shrank the row pitch
    # from 53px to 40px and left the bottom third of every frame empty, while
    # the build still reported success.
    before = _text_geometry(client, container=ROOT)
    _run(client, f"""
    sc = op({SCRIPT_TOP_NAME!r})
    was = bool(sc.bypass) if sc is not None else False
    if sc is not None:
        sc.bypass = True
    return repr(was)
""")

    say("probing natural glyph advance")
    # Measure across the whole grid, not between neighbouring cells. TouchDesigner
    # lays glyphs on integer pixels, so a single step carries a rounding error that
    # the solve then multiplies by the number of rows: one-step gave 39.27px per
    # row where the true pitch is 40.05, and the bottom of the frame came out 14px
    # adrift. Corner to corner, divided by the span, averages that away.
    last_r, last_c = g.vrows - 1, g.cols - 1
    p00 = probe((0, 0), 0.0, 0.0)
    p0N = probe((0, last_c), 0.0, 0.0)
    pN0 = probe((last_r, 0), 0.0, 0.0)
    if None in (p00, p0N, pN0) or last_r < 1 or last_c < 1:
        return {"ok": False, "error": "probe glyphs did not render; "
                                      "check the font name and that the Script TOP is bypassed"}
    adv_x0 = (p0N[0] - p00[0]) / last_c
    adv_y0 = (pN0[1] - p00[1]) / last_r

    say(f"natural advance {adv_x0:.3f}px x {adv_y0:.3f}px; want {cell_w:.3f} x {cell_h:.3f}")

    # Neither parameter's effect on the advance can be assumed: `trackingx` has
    # no documented unit at all, and `linespacing` is nominally in pixels but
    # does not move the row pitch 1:1 -- taking that on faith left the bottom
    # corner 14px out of its cell. So measure both slopes the same way: nudge
    # the parameter by a known amount and see how far the advance actually moves.
    probe_t = 0.1
    p0Nt = probe((0, last_c), probe_t, 0.0)
    p00t = probe((0, 0), probe_t, 0.0)
    if p0Nt is None or p00t is None:
        return _give_up(client, before, 'tracking probe did not render')
    k_x = (((p0Nt[0] - p00t[0]) / last_c) - adv_x0) / probe_t
    if abs(k_x) < 1e-6:
        return _give_up(client, before, 'tracking has no measurable effect on advance')
    tracking = (cell_w - adv_x0) / k_x

    probe_s = 10.0
    pN0s = probe((last_r, 0), 0.0, probe_s)
    p00s = probe((0, 0), 0.0, probe_s)
    if pN0s is None or p00s is None:
        return _give_up(client, before, 'line spacing probe did not render')
    k_y = (((pN0s[1] - p00s[1]) / last_r) - adv_y0) / probe_s
    if abs(k_y) < 1e-6:
        return _give_up(client, before, 'line spacing has no measurable effect on advance')
    spacing = (cell_h - adv_y0) / k_y
    say(f"advance slopes: {k_x:.4f}px per tracking unit, "
        f"{k_y:.4f}px per spacing unit")

    # with the advances right, shift the whole block so cell (0,0) sits centred
    say(f"solved tracking {tracking:.6f}, linespacing {spacing:.4f}; solving offset")
    base = probe((0, 0), tracking, spacing)  # noqa: E501
    if base is None:
        return _give_up(client, before, 'offset probe did not render')
    posx = cell_w / 2.0 - base[0]
    posy = -(cell_h / 2.0 - base[1])      # TD's positiony is +up, pixels are +down

    final = probe((0, 0), tracking, spacing, posx, posy)
    far = probe((g.vrows - 1, g.cols - 1), tracking, spacing, posx, posy)
    res = {"ok": True, "trackingx": round(tracking, 6),
           "linespacing": round(spacing, 4),
           "positionx": round(posx, 4), "positiony": round(posy, 4),
           "cell": (round(cell_w, 3), round(cell_h, 3))}
    if final:
        res["residual_near"] = (round(final[0] - cell_w / 2, 2),
                                round(final[1] - cell_h / 2, 2))
    if far:
        res["residual_far"] = (
            round(far[0] - (g.cols - 0.5) * cell_w, 2),
            round(far[1] - (g.vrows - 0.5) * cell_h, 2))
        worst = max(abs(v) for v in res["residual_far"])
        if worst > min(cell_w, cell_h) / 3.0:
            res["ok"] = False
            res["error"] = (f"corner glyph is {worst:.1f}px off its cell centre; "
                            "the solve did not converge")
    if res["ok"]:
        apply_text_geometry(client, tracking, spacing, posx, posy)
    elif before:
        say("calibration did not converge; putting the previous geometry back")
        apply_text_geometry(client, **before)
    _run(client, f"""
    sc = op({SCRIPT_TOP_NAME!r})
    if sc is not None:
        sc.bypass = False
    return 'ok'
""")
    say(f"calibration {'ok' if res['ok'] else 'FAILED'}: {res}")
    return res


# ---------------------------------------------------------------------- build

def build(client, cfg, progress=None, container: str = ROOT,
          push: bool = True, calibrate: bool = True) -> dict:
    """Construct the whole network. Safe to re-run: `create` replaces by name.

    `container` exists because the MCP server this is speaking through lives
    *inside* the project being built (`/project1/td_mcp_server`). Building into a
    sub-container is how a build is exercised without demolishing the network
    that is answering the call -- which is also how it is tested.

    `push` and `calibrate` are off for that case: `sync` addresses `/project1` by
    name, and calibration needs the real Script TOP bypassed.
    """
    from ... import sync

    say = progress or (lambda m: None)
    specs = network(cfg)

    say("quiescing TouchDesigner")
    sync.quiesce(client)

    say("checking every operator type resolves")
    unknown = check_types(client, specs)
    if unknown:
        raise RuntimeError(f"unknown TD type constants: {unknown}")

    problems: list[str] = []
    problems += create_ops(client, specs, say, container)
    drop_autocreated(client, specs, say, container)
    load_analysis_component(client, cfg, say, container)
    problems += wire_ops(client, specs, say, container)
    problems += apply_exprs(client, specs, say, container)

    result = {"built": len(specs), "problems": problems}

    if push:
        say("pushing field script, params and cues")
        sync.push_field(client, cfg)
        sync.push_params(client, cfg)
        if calibrate:
            cal = calibrate_text(client, cfg, say)
            result["calibration"] = cal
            # A build that could not place the glyphs is not a successful build.
            # Silently carrying on left the row pitch at the font's natural
            # advance, which is smaller than a cell, so the grid drew short of
            # the frame and the bottom of every render was empty.
            if not cal.get("ok"):
                problems.append(
                    "text calibration failed: " + str(cal.get("error", "unknown"))
                    + " -- glyph placement is whatever it was before, so the "
                      "grid may not line up with the frame")
        say("resuming")
        sync.resume(client)

    result["discrepancies"] = verify(client, cfg, container)
    return result


def check_types(client, specs) -> list[str]:
    """Fail before creating anything if a type constant does not exist.

    `compositeTOP` vs `compTOP` and friends are easy to get wrong, and a failure
    halfway through leaves a half-built network.
    """
    names = sorted({s.type for s in specs})
    out = _run(client, f"""
    import td
    missing = [n for n in {names!r} if not hasattr(td, n)]
    return repr(missing)
""")
    try:
        return eval(out.strip())
    except Exception:
        return []


# --------------------------------------------------------------------- verify

def verify(client, cfg, container: str = ROOT) -> list[str]:
    """Diff the live network against `network(cfg)`.

    Reads each parameter's mode before comparing: a parameter switched back to a
    constant can still carry a stale expression, and treating that as active is
    exactly the bug that makes the `map` tool misreport this network.
    """
    specs = network(cfg)
    want = {
        s.name: {
            "type": s.type,
            "inputs": s.inputs,
            "params": {k: v for k, v in s.params.items()},
            "exprs": s.exprs,
        }
        for s in specs
    }
    out = _run(client, f"""
    import td
    want = {want!r}
    root = op({container!r})
    bad = []
    for name, spec in want.items():
        o = root.op(name)
        if o is None:
            bad.append(name + ': missing')
            continue
        if o.OPType != getattr(td, spec['type']).__name__ and o.type not in spec['type'].lower():
            pass
        got_in = [i.name if i else None for i in o.inputs]
        exp_in = [s.split('/')[-1] for s in spec['inputs']]
        if got_in != exp_in:
            bad.append('%s: inputs %r != %r' % (name, got_in, exp_in))
        for k, v in spec['params'].items():
            if not hasattr(o.par, k):
                bad.append('%s: no param %s' % (name, k))
                continue
            p = getattr(o.par, k)
            if 'EXPRESSION' in str(p.mode).upper():
                bad.append('%s.%s is an expression, expected constant %r' % (name, k, v))
                continue
            got = p.eval()
            if not isinstance(got, (bool, int, float, str)):
                got = p.val          # callbacks/dat evaluate to an OP, not a name
            if isinstance(v, float) or isinstance(got, float):
                try:
                    if abs(float(got) - float(v)) > 1e-4:
                        bad.append('%s.%s = %r, expected %r' % (name, k, got, v))
                except (TypeError, ValueError):
                    if got != v:
                        bad.append('%s.%s = %r, expected %r' % (name, k, got, v))
            elif got != v:
                bad.append('%s.%s = %r, expected %r' % (name, k, got, v))
        for k, e in spec['exprs'].items():
            if not hasattr(o.par, k):
                bad.append('%s: no param %s' % (name, k))
                continue
            p = getattr(o.par, k)
            if 'EXPRESSION' not in str(p.mode).upper():
                bad.append('%s.%s is a constant, expected expression' % (name, k))
            elif p.expr != e:
                bad.append('%s.%s expr %r != %r' % (name, k, p.expr, e))
    aa = root.op({ANALYSIS_COMP!r})
    if aa is None:
        bad.append('aa: missing')
    elif aa.op('out1') is None:
        bad.append('aa: no out1')
    # Operators outside the spec are reported, but prefixed so callers can tell
    # them apart from real faults: a project may legitimately carry unrelated
    # work, and their presence must not force a rebuild on every run.
    extra = [c.name for c in root.children
             if c.name not in want and c.name not in {PROTECTED!r}
             and c.name != {ANALYSIS_COMP!r}]
    if extra:
        bad.append('note: %d operators outside the spec: %r'
                   % (len(extra), sorted(extra)[:12]))
    return repr(bad)
""", timeout=180.0)
    try:
        return eval(out.strip())
    except Exception:
        return [f"verify could not parse result: {out[:300]}"]
