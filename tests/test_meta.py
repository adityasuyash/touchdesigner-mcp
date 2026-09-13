"""Tests that close a whole class of defect rather than one instance.

Each of these would have caught a bug that actually shipped, and would go on
catching its successors. They are cheap, they need nothing installed, and they
are the highest-value tests in the suite.
"""

from __future__ import annotations

import ast
import collections
from pathlib import Path

import pytest

from lyricfield import types as types_mod
from lyricfield.types.lyric_grid import params as P

REPO = Path(__file__).resolve().parents[1]
PACKAGE = REPO / "lyricfield"


# --------------------------------------------------------------- definitions

def _modules():
    return sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.relative_to(PACKAGE)))
def test_no_duplicate_top_level_definitions(path: Path):
    """A second `def foo` silently replaces the first, and nothing complains.

    This happened: `analysis.vocal_entry` was defined twice, and the second --
    a thinner implementation -- shadowed a carefully threshold-tuned first. The
    dead one kept its docstring, so reading the file suggested behaviour the
    program did not have.
    """
    tree = ast.parse(path.read_text())
    names = [n.name for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
    dupes = sorted(n for n, c in collections.Counter(names).items() if c > 1)
    assert not dupes, f"{path.relative_to(PACKAGE)} defines these twice: {dupes}"


# ------------------------------------------------------------------- tunables

def _declared_fields():
    """Every tunable a type declares, as {name: default}."""
    out = {}
    for section in P.Params().__dataclass_fields__:
        obj = getattr(P.Params(), section)
        for name, value in vars(obj).items():
            out[name] = value
    return out


def test_every_tunable_has_a_range():
    """A tunable with no declared bounds gets invented ones in the UI.

    The fallback rescaled the maximum from whatever the current value happened
    to be, so a slider never settled in the same place twice and a minimum of
    zero put `offset` out of reach below zero.
    """
    numeric = {k: v for k, v in _declared_fields().items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)}
    missing = sorted(set(numeric) - set(P.RANGES))
    assert not missing, f"declared but unbounded: {missing}"


def test_no_range_without_a_tunable():
    """The reverse: a range for a parameter that no longer exists is a lie."""
    stray = sorted(set(P.RANGES) - set(_declared_fields()))
    assert not stray, f"RANGES names parameters that do not exist: {stray}"


def test_defaults_sit_inside_their_ranges():
    bad = []
    for name, value in _declared_fields().items():
        if name not in P.RANGES or not isinstance(value, (int, float)):
            continue
        lo, hi, _step = P.RANGES[name]
        if not (lo <= value <= hi):
            bad.append(f"{name}={value} outside ({lo}, {hi})")
    assert not bad, bad


def test_ranges_are_ordered():
    bad = [f"{k}: {lo} !< {hi}" for k, (lo, hi, _s) in P.RANGES.items() if lo >= hi]
    assert not bad, bad


# ------------------------------------------------------------------- controls

def test_control_leads_are_their_own_targets():
    for c in P.CONTROLS:
        assert c.lead in c.targets, f"{c.key}: lead {c.lead} is not one of its targets"


def test_control_targets_resolve_and_stay_in_range():
    p = P.Params()
    bad = []
    for c in P.CONTROLS:
        for path, (a, b) in c.targets.items():
            section, name = path.split(".")
            if not hasattr(getattr(p, section, object()), name):
                bad.append(f"{c.key}: {path} does not exist")
                continue
            if name not in P.RANGES:
                bad.append(f"{c.key}: {path} has no declared range")
                continue
            lo, hi, _ = P.RANGES[name]
            # a..b may be inverted on purpose (a duration where more is calmer)
            if not (lo <= min(a, b) and max(a, b) <= hi):
                bad.append(f"{c.key}: {path} spans ({a}, {b}) outside ({lo}, {hi})")
    assert not bad, bad


@pytest.mark.parametrize("value", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_any_control_position_leaves_a_valid_config(value):
    """`reconcile` promises that after it, `validate()` has nothing to say."""
    for c in P.CONTROLS:
        p = P.Params()
        P.apply_control(p, c.key, value)
        assert p.validate() == [], f"{c.key}={value} produced {p.validate()}"


def test_controls_compose_without_producing_an_invalid_config():
    """Moving several controls is the normal case, and they interact --
    brightness and glow stack at the output, and they belong to two controls."""
    import itertools
    steps = [0.0, 0.5, 1.0]
    for combo in itertools.product(steps, repeat=3):
        p = P.Params()
        for key, v in zip(("brightness", "glow", "beat"), combo):
            P.apply_control(p, key, v)
        assert p.validate() == [], f"{combo} produced {p.validate()}"


def test_reconcile_is_idempotent():
    import copy
    for c in P.CONTROLS:
        p = P.Params()
        P.apply_control(p, c.key, 1.0)
        P.reconcile(p)
        once = copy.deepcopy(p)
        P.reconcile(p)
        assert p == once, f"reconcile moved again after {c.key}"


def test_unknown_control_is_refused():
    with pytest.raises(KeyError):
        P.apply_control(P.Params(), "nonsense", 0.5)


# ---------------------------------------------------------------- type registry

def test_every_registered_type_answers_the_contract():
    """`_discover` swallows every import error, so a type that fails to import
    simply vanishes. Asserting the registry is the cheapest canary for that."""
    listed = types_mod.list_types()
    assert listed, "no video types registered at all"
    for vt in listed:
        p = vt.default_params()
        assert vt.slug and vt.name
        assert vt.family in (types_mod.LYRIC, types_mod.BEATSYNC)
        assert isinstance(vt.ranges(), dict)
        assert isinstance(vt.section_names(), tuple)
        assert p.validate() == [], f"{vt.slug} ships an invalid default config"


def test_the_default_type_exists():
    assert types_mod.get_type(types_mod.DEFAULT_TYPE) is not None
