"""Swarm: words fly in, settle, and are knocked apart.

Physical, but not a physical simulation. Bullet and the Particle SOP step per
cook, so a dropped frame or a seek changes what they produce; this re-runs a
spring-damper from the line's own start every frame instead.
"""

from __future__ import annotations

import types as pytypes

import numpy as np
import pytest

from lyricfield import types as types_mod
from lyricfield.types.swarm import params as P

WORDS = ["every", "word", "finds", "its", "place"]


@pytest.fixture
def sw():
    src = types_mod.get_type("swarm").field_source()
    mod = pytypes.ModuleType("swarm_under_test")
    mod.__dict__["np"] = np
    exec(compile(src, "field.py", "exec"), mod.__dict__)
    mod.S.clear()
    return mod


def _worst(sw, pos):
    tgt = sw._targets(len(pos))
    return max(((px - tx) ** 2 + (py - ty) ** 2) ** 0.5
               for (px, py), (tx, ty) in zip(pos, tgt))


def test_it_is_a_lyric_type():
    vt = types_mod.get_type("swarm")
    assert vt.family == types_mod.LYRIC
    assert vt.needs_lyrics is True


def test_it_does_not_borrow_the_grid_renderer():
    from pathlib import Path
    here = Path(types_mod.__file__).parent / "swarm"
    for name in ("build.py", "params.py", "field.py"):
        assert "from ..lyric_grid" not in (here / name).read_text()


# ------------------------------------------------------------- determinism

def test_a_frame_depends_only_on_its_own_timestamp(sw):
    """The integrator is re-run from the line's start rather than carried from
    frame to frame. That is what makes a seek land on exactly the frame a full
    playthrough would -- the thing Bullet and the Particle SOP cannot promise.
    """
    direct = sw._settle(WORDS, 0.0, 2.0, [])
    for t in (0.2, 0.5, 1.1, 1.7):           # arrive by a different history
        sw._settle(WORDS, 0.0, t, [])
    assert sw._settle(WORDS, 0.0, 2.0, []) == direct


def test_the_throw_direction_is_decided_by_index_not_by_chance(sw):
    """Random per frame would make the entrance different on every render."""
    a = sw._settle(WORDS, 0.0, 0.02, [])
    b = sw._settle(WORDS, 0.0, 0.02, [])
    assert a == b


def test_the_physics_does_not_depend_on_the_frame_rate(sw):
    """The step is fixed, not the frame interval, so a render at a different
    rate is the same picture."""
    assert sw.DT == pytest.approx(1.0 / 120.0)


# ------------------------------------------------------------- the flight

def test_words_start_away_from_home_and_arrive(sw):
    early = _worst(sw, sw._settle(WORDS, 0.0, 0.05, []))
    late = _worst(sw, sw._settle(WORDS, 0.0, 2.0, []))
    assert early > 0.3, "the words did not come from anywhere"
    assert late < 0.02, f"the words never arrived: {late:.4f} from home"


def test_the_line_keeps_settling_rather_than_ringing_forever(sw):
    at2 = _worst(sw, sw._settle(WORDS, 0.0, 2.0, []))
    at4 = _worst(sw, sw._settle(WORDS, 0.0, 4.0, []))
    assert at4 < at2


def test_a_kick_knocks_a_settled_line_apart(sw):
    calm = _worst(sw, sw._settle(WORDS, 0.0, 2.1, []))
    hit = _worst(sw, sw._settle(WORDS, 0.0, 2.1, [2.0]))
    assert hit > calm * 3, f"calm {calm:.4f} vs struck {hit:.4f}"


def test_words_are_laid_out_in_rows(sw):
    tgt = sw._targets(5)
    ys = sorted({round(y, 4) for _x, y in tgt})
    assert len(ys) == 2, f"five words at three to a row should make two rows: {ys}"


def test_a_word_thrown_off_frame_is_dropped_not_clamped(sw):
    """Clamped, off-frame words pile into a stripe down the edge."""
    spec = sw._spec(["a", "b"], [(0.5, 0.5), (9.0, 9.0)])
    assert len(spec.strip().split("\n")) == 2      # header plus one word


def test_the_spec_is_one_row_per_word_lower_left(sw):
    spec = sw._spec(["hi"], [(0.25, 0.25)])
    header, row = spec.split("\n")
    assert header.split("\t") == ["x", "y", "text"]
    x, y, word = row.split("\t")
    assert word == "hi"
    assert int(x) == int(0.25 * sw.WIDTH)
    assert int(y) == int(0.75 * sw.HEIGHT), "the origin is not lower-left"


# ------------------------------------------------------------- the defaults

def test_the_defaults_are_a_valid_config():
    assert P.Params().validate() == []


def test_treacle_is_refused():
    """Overshoot is wanted; a word crawling home is not."""
    p = P.Params()
    p.flight.damp = 500.0
    assert p.validate() != []
    P.reconcile(p)
    assert p.validate() == []


def test_two_sections_never_share_a_tunable_name():
    p = P.Params()
    seen = {}
    for sec in p.__dataclass_fields__:
        for f in getattr(p, sec).__dataclass_fields__:
            assert f not in seen, f"{f} in both {seen[f]} and {sec}"
            seen[f] = sec
