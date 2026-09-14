"""Two renderers, one picture.

A beat look used to be able to sit behind words only when it *was* the character
grid the words are drawn in, because it arrived as a section of `lyric_grid`'s
own tunables. Five of seven beat renderers could therefore never be a layer, and
the gallery had to change the meaning of its second row to say so.

Compositing removes the question, and these are the properties that make it
safe: every pair builds, the containers do not collide, the words stay the
brightest thing on screen, and either half may be missing.
"""

from __future__ import annotations

import itertools

import pytest

from lyricfield import compose
from lyricfield import types as types_mod
from lyricfield.config import Config

LYRIC = [t.slug for t in types_mod.list_types() if t.family == types_mod.LYRIC]
BEAT = [t.slug for t in types_mod.list_types() if t.family == types_mod.BEATSYNC]
PAIRS = list(itertools.product(LYRIC, BEAT))


def _cfg(front, back):
    c = Config(type=front)
    return c.with_back(back)


def _network_of(slug):
    """A renderer's OpSpec list, wherever it keeps it.

    `pulse_grid` and `swell` delegate their whole build to `lyric_grid` and do
    not re-export `network`, which is the point of delegating.
    """
    from importlib import import_module

    mod = import_module(f"lyricfield.types.{slug}.build")
    fn = getattr(mod, "network", None)
    if fn is not None:
        return fn
    from lyricfield.types.lyric_grid.build import network
    return network


# --------------------------------------------------------------- every pair

@pytest.mark.parametrize("front,back", PAIRS, ids=[f"{a}+{b}" for a, b in PAIRS])
def test_every_pair_of_renderers_composes(front, back):
    """The claim the whole change rests on. Not "the two grid ones work"."""
    c = _cfg(front, back)
    specs = compose.network(c)
    names = [s.name for s in specs]
    assert "out" in names
    assert "mix" in names, f"{front}+{back} did not produce a mix"


@pytest.mark.parametrize("front,back", PAIRS, ids=[f"{a}+{b}" for a, b in PAIRS])
def test_every_pair_builds_its_two_networks(front, back):
    """Each side's `network()` has to succeed with the OTHER side's config
    alongside it -- which is only true because a renderer is built from its own
    params into its own container."""
    c = _cfg(front, back)
    assert _network_of(front)(c)
    assert _network_of(back)(compose._BackView(c))


@pytest.mark.parametrize("front,back", PAIRS, ids=[f"{a}+{b}" for a, b in PAIRS])
def test_the_layer_is_built_from_its_own_tunables(front, back):
    """The bug this design exists to make impossible: building the layer from
    the front renderer's parameters. A `build()` reads `cfg.<section>`, so
    handing it the real Config would draw the beat look with the lyric look's
    numbers."""
    c = _cfg(front, back)
    view = compose._BackView(c)
    assert view.video_type.slug == back
    assert view.params is c.back_params
    assert view.as_params() == c.back_as_params()
    # ... and the song's measured facts still reach it.
    assert "duration" in view.as_params()


# ------------------------------------------------------- either half missing

def test_words_alone_are_the_whole_picture():
    c = _cfg("monument", None)
    names = {s.name: s for s in compose.network(c)}
    assert names["out"].inputs == ["mix_words"]
    assert names["mix_words"].params["top"] == "words/out"
    assert "mix_dim" not in names


def test_a_beat_look_alone_is_the_whole_picture():
    c = Config(type="rings")
    c.type = ""                       # nothing drawing words
    c.with_back("rings")
    names = {s.name: s for s in compose.network(c)}
    assert names["out"].inputs == ["mix_dim"]


def test_nothing_picked_still_produces_an_output():
    """`render` records `/project1/out` unconditionally. A missing operator
    there is a timeout, not an error message."""
    c = Config(type="monument")
    c.type = ""
    names = {s.name for s in compose.network(c)}
    assert "out" in names


# ------------------------------------------------------------ the brightness

def test_the_layer_can_never_outshine_the_words():
    """A beat look tuned to BE the picture is far too bright to sit under one,
    and brightness stacks at the output -- the defect this project has fixed
    three times."""
    assert compose.layer_brightness(1.0) <= compose.CEILING
    assert compose.layer_brightness(9.9) <= compose.CEILING
    assert compose.layer_brightness(-3) == 0.0


def test_strength_moves_the_layer_within_that_bound():
    assert compose.layer_brightness(0.0) < compose.layer_brightness(0.5)
    assert compose.layer_brightness(0.5) < compose.layer_brightness(1.0)


def test_the_two_halves_are_mixed_by_taking_the_brighter():
    """Neither of the obvious alternatives works.

    `over` does nothing: a lyric renderer draws its own black ground, so its
    frame is opaque and hides the layer entirely -- measured, a live layer at
    0.102 came out of the mix at exactly the words' own 0.0196. `add` stacks,
    which is the defect this project has fixed three times.

    `maximum` leaves the words at their own brightness and lets the layer fill
    the black between them.
    """
    c = _cfg("monument", "rings")
    mix = next(s for s in compose.network(c) if s.name == "mix")
    assert mix.params["operand"] == "maximum"
    assert mix.inputs[0] == "mix_words", "the words must be the first input"


# --------------------------------------------------------------- containers

def test_the_halves_are_reached_by_select_rather_than_wired_across():
    """A TOP inside a base COMP cannot be wired to one outside it, and a COMP is
    not a valid TOP input either. The `wire` tool reports success for the first
    and leaves the input unconnected -- measured: a live layer at 0.31 arriving
    as 0.0 through a Level TOP that said it was wired."""
    c = _cfg("monument", "rings")
    names = {s.name: s for s in compose.network(c)}
    assert names["mix_beat"].type == "selectTOP"
    assert names["mix_words"].type == "selectTOP"
    assert names["mix_beat"].params["top"] == "beat/out"
    assert not names["mix_beat"].inputs, "a Select TOP takes a path, not a wire"


def test_the_two_containers_are_separate():
    c = _cfg("monument", "rings")
    assert compose.container_for(c, compose.WORDS) != \
        compose.container_for(c, compose.BEAT)


def test_a_renderer_addresses_its_operators_by_bare_name():
    """What makes building into a container work at all. A field script that
    reached for `/project1/lyrics` would read the other half's table."""
    import re

    # An absolute path handed to `op()`. Prose may mention `/project1` -- what
    # would break is code reaching for it.
    absolute = re.compile(r"""\bop\(\s*['"]/""")
    for vt in types_mod.list_types():
        src = vt.field_source()
        if not src:
            continue
        hits = absolute.findall(src)
        assert not hits, (
            f"{vt.slug}'s field script passes an absolute path to op(); built "
            f"into a container it would read the other half's tables")


# ------------------------------------------- the mechanism this replaced

def test_no_shipped_look_switches_on_the_old_backdrop():
    """`lyric_grid` still carries a `backdrop` section from when a layer was a
    part of ITS tunables rather than a renderer of its own. It is inert -- the
    default is off and nothing ships with it on -- and it is scheduled for
    deletion.

    Until then this is the guard that matters: a look that switched it on would
    draw lyric_grid's own ambient field AND have a composited layer under it,
    which is two backdrops and no way to tell which is which.
    """
    from lyricfield import styles as styles_mod

    hot = []
    for st in styles_mod.list_styles():
        bd = getattr(st.params, "backdrop", None)
        if bd is not None and getattr(bd, "back_level", 0.0) > 0.0:
            hot.append(f"{st.type}/{st.slug}")
    assert not hot, (
        f"these looks switch on the superseded backdrop section: {hot}")


def test_the_layer_is_not_reached_through_the_front_renderer_any_more():
    """`run` used to translate a beat look into `lyric_grid`'s backdrop, which
    is why only two of seven could ever be one."""
    import inspect

    from lyricfield import run as run_mod

    src = inspect.getsource(run_mod._apply_backdrop)
    assert "backdrop_from" not in src
    assert "with_back" in src
