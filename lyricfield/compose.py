"""Two renderers, one picture.

A beat look used to be able to sit behind words only if it *was* the character
grid the words are drawn in: `lyric_grid` carried a `backdrop` section, and a
beat renderer's parameters were mapped into it. That works for `pulse_grid` and
`swell`, which are the same grid, and cannot work for `rings`, `strata`,
`scope`, `halftone` or `spectrum`, whose pictures are not made of cells at all.
So the gallery had to change the meaning of its second row depending on the
first, and five of seven beat looks could never be a layer.

Compositing removes the question. Each renderer is built into its own container
and the two are mixed at the end:

    /project1/beat/out  -> mix_dim (Level, strength) --\\
                                                        mix -> out
    /project1/words/out -----------------------------/

Two facts already true of the codebase make this cheap. Every renderer's
`build()` takes a `container` and its network ends in an `out` null TOP; and
every field script addresses its operators by BARE NAME -- `op('lyrics')`,
`op('spec0')` -- so it runs correctly wherever it is built. `styles`' preview
capture has been relying on both for a while.

Either side may be absent. A beat look with no words is the whole picture, words
with nothing behind them are the whole picture, and `out` is wired to match.
"""

from __future__ import annotations

from .types._build import OpSpec, ROOT, create_ops, wire_ops

WORDS = "words"
BEAT = "beat"

# The layer behind may never be brighter than this share of the words. A beat
# look tuned to BE the picture is tuned far too bright to sit under one -- that
# is the whole reason the old mechanism rescaled rather than copied -- and
# brightness stacks at the output, which this project has been bitten by three
# times.
CEILING = 0.55


def path(container: str, name: str = "") -> str:
    """`/project1/beat/out`, from ("/project1/beat", "out")."""
    return f"{container}/{name}" if name else container


def container_for(cfg, which: str) -> str:
    return f"{ROOT}/{which}"


def layer_brightness(strength: float) -> float:
    """What the Level TOP on the beat layer is set to.

    Bounded rather than trusted: a style is free to ask for anything, and the
    words have to stay the brightest thing on screen.
    """
    return round(max(0.0, min(1.0, float(strength))) * CEILING, 4)


def network(cfg) -> list[OpSpec]:
    """The mix, and nothing else -- each renderer builds its own container."""
    lyric = bool(cfg.type)
    beat = bool(cfg.back_type)
    w = getattr(cfg.params, "stage", None) or getattr(cfg.params, "grid", None) \
        or getattr(cfg.params, "frame", None)
    width = int(getattr(w, "width", 720))
    height = int(getattr(w, "height", 1280))
    frame = {"outputresolution": "custom", "resolutionw": width,
             "resolutionh": height, "resmult": False}

    # A TOP inside a base COMP cannot be wired to one outside it, and a COMP is
    # not a valid TOP input either -- both were tried, and the `wire` tool
    # reported success for the first while leaving the input unconnected, which
    # is the failure mode this project keeps meeting. A Select TOP pulls a TOP
    # by path from anywhere and is the idiomatic answer; `lyric_grid` already
    # uses one.
    specs: list[OpSpec] = []
    if lyric:
        specs.append(OpSpec("mix_words", "selectTOP", (-600, -400),
                            params={**frame, "top": f"{WORDS}/out"}))
    if beat:
        specs.append(OpSpec("mix_beat", "selectTOP", (-600, -200),
                            params={**frame, "top": f"{BEAT}/out"}))
        specs.append(OpSpec("mix_dim", "levelTOP", (-400, -200),
                            params={**frame,
                                    "brightness1": layer_brightness(
                                        cfg.back_strength)},
                            inputs=["mix_beat"]))
    if lyric and beat:
        # `maximum`, and neither of the two obvious alternatives.
        #
        # `over` does nothing at all: a lyric renderer draws its own black
        # ground, so its frame is fully opaque and covers the layer completely
        # -- measured, a live layer at 0.102 came out of the mix at exactly the
        # words' own 0.0196. `add` would work but stacks, which is the defect
        # this project has fixed three times: the words would be lifted by
        # whatever happened to be behind them at that instant.
        #
        # `maximum` takes the brighter of the two per pixel. The words keep
        # their own brightness exactly, because they are brighter than a layer
        # capped at CEILING; the layer fills the black between them. Nothing
        # stacks, so nothing needs clamping afterwards.
        specs.append(OpSpec("mix", "compositeTOP", (-200, -400),
                            params={**frame, "operand": "maximum"},
                            inputs=["mix_words", "mix_dim"]))
        src = "mix"
    elif lyric:
        src = "mix_words"
    elif beat:
        src = "mix_dim"
    else:                                   # nothing picked at all
        specs.append(OpSpec("mix_black", "constantTOP", (-200, -400),
                            params=frame))
        src = "mix_black"
    specs.append(OpSpec("out", "nullTOP", (0, -400),
                        params={"resmult": False}, inputs=[src]))
    return specs


def build(client, cfg, progress=None) -> dict:
    """Build both renderers into their own containers, then the mix.

    Returns what was built, so a caller can say which halves are live.
    """
    say = progress or (lambda m: None)
    out: dict = {"words": "", "beat": "", "problems": []}

    if cfg.type:
        box = container_for(cfg, WORDS)
        say(f"building {cfg.video_type.name} into {box}")
        _make(client, box)
        r = cfg.video_type.build(client, cfg, progress=say, container=box,
                                 push=False)
        out["words"] = box
        out["problems"] += list(r.get("problems") or [])

    if cfg.back_type:
        box = container_for(cfg, BEAT)
        say(f"building {cfg.back_video_type.name} into {box} as the layer")
        _make(client, box)
        # The layer is built from ITS OWN params, which is the whole point: it
        # is a renderer, not a section of somebody else's.
        shim = _BackView(cfg)
        r = cfg.back_video_type.build(client, shim, progress=say, container=box,
                                      push=False)
        out["beat"] = box
        out["problems"] += list(r.get("problems") or [])

    say("wiring the mix")
    specs = network(cfg)
    out["problems"] += create_ops(client, specs, progress=say, container=ROOT)
    out["problems"] += wire_ops(client, specs, progress=say, container=ROOT)
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


class _BackView:
    """The config as the layer's renderer sees it: its own params, same song.

    A `build()` reads `cfg.<section>` and `cfg.track`, so handing it the real
    Config would build the layer from the FRONT renderer's tunables. This is
    four lines rather than a second Config because everything else -- saving,
    validating, the UI -- must keep seeing one config with a layer in it.
    """

    def __init__(self, cfg):
        self._cfg = cfg
        self.type = cfg.back_type
        self.track = cfg.track
        self.params = cfg.back_params

    @property
    def video_type(self):
        return self._cfg.back_video_type

    def as_params(self) -> dict:
        return self._cfg.back_as_params()

    def __getattr__(self, name):
        params = self.__dict__.get("params")
        if params is not None and hasattr(params, name):
            return getattr(params, name)
        raise AttributeError(name)
