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

# Every registered type, not just the first one written. A meta-test that only
# covers one type stops being a meta-test the moment a second one exists.
TYPES = list(types_mod.list_types())
TYPE_IDS = [vt.slug for vt in TYPES]


def _params_module(vt):
    import importlib
    return importlib.import_module(f"lyricfield.types.{vt.slug}.params")

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

def _declared_fields(vt):
    """Every tunable a type declares, as {name: default}."""
    out = {}
    p = vt.default_params()
    for section in p.__dataclass_fields__:
        for name, value in vars(getattr(p, section)).items():
            out[name] = value
    return out


@pytest.mark.parametrize("vt", TYPES, ids=TYPE_IDS)
def test_every_tunable_has_a_range(vt):
    """A tunable with no declared bounds gets invented ones in the UI.

    The fallback rescaled the maximum from whatever the current value happened
    to be, so a slider never settled in the same place twice, and clamped every
    minimum to zero, putting `offset` out of reach below zero.
    """
    ranges = vt.ranges()
    numeric = {k: v for k, v in _declared_fields(vt).items()
               if isinstance(v, (int, float)) and not isinstance(v, bool)}
    missing = sorted(set(numeric) - set(ranges))
    assert not missing, f"{vt.slug} declares these unbounded: {missing}"


@pytest.mark.parametrize("vt", TYPES, ids=TYPE_IDS)
def test_no_range_without_a_tunable(vt):
    """The reverse: a range for a parameter that no longer exists is a lie."""
    stray = sorted(set(vt.ranges()) - set(_declared_fields(vt)))
    assert not stray, f"{vt.slug} bounds parameters that do not exist: {stray}"


@pytest.mark.parametrize("vt", TYPES, ids=TYPE_IDS)
def test_defaults_sit_inside_their_ranges(vt):
    ranges = vt.ranges()
    bad = []
    for name, value in _declared_fields(vt).items():
        if name not in ranges or not isinstance(value, (int, float)):
            continue
        lo, hi, _step = ranges[name]
        if not (lo <= value <= hi):
            bad.append(f"{name}={value} outside ({lo}, {hi})")
    assert not bad, f"{vt.slug}: {bad}"


@pytest.mark.parametrize("vt", TYPES, ids=TYPE_IDS)
def test_ranges_are_ordered(vt):
    bad = [f"{k}: {lo} !< {hi}" for k, (lo, hi, _s) in vt.ranges().items() if lo >= hi]
    assert not bad, f"{vt.slug}: {bad}"


# ------------------------------------------------------------------- controls

@pytest.mark.parametrize("vt", TYPES, ids=TYPE_IDS)
def test_control_leads_are_their_own_targets(vt):
    P = _params_module(vt)
    for c in getattr(P, "CONTROLS", ()):
        assert c.lead in c.targets, f"{vt.slug}/{c.key}: lead is not a target"


@pytest.mark.parametrize("vt", TYPES, ids=TYPE_IDS)
def test_control_targets_resolve_and_stay_in_range(vt):
    P = _params_module(vt)
    p, ranges, bad = vt.default_params(), vt.ranges(), []
    for c in getattr(P, "CONTROLS", ()):
        for path, (a, b) in c.targets.items():
            section, name = path.split(".")
            if not hasattr(getattr(p, section, object()), name):
                bad.append(f"{c.key}: {path} does not exist")
                continue
            if name not in ranges:
                bad.append(f"{c.key}: {path} has no declared range")
                continue
            lo, hi, _ = ranges[name]
            # a..b may be inverted on purpose (a duration where more is calmer)
            if not (lo <= min(a, b) and max(a, b) <= hi):
                bad.append(f"{c.key}: {path} spans ({a}, {b}) outside ({lo}, {hi})")
    assert not bad, f"{vt.slug}: {bad}"


@pytest.mark.parametrize("vt", TYPES, ids=TYPE_IDS)
@pytest.mark.parametrize("value", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_any_control_position_leaves_a_valid_config(vt, value):
    """`reconcile` promises that after it, `validate()` has nothing to say."""
    P = _params_module(vt)
    for c in getattr(P, "CONTROLS", ()):
        p = vt.default_params()
        P.apply_control(p, c.key, value)
        assert p.validate() == [], f"{vt.slug}/{c.key}={value}: {p.validate()}"


@pytest.mark.parametrize("vt", TYPES, ids=TYPE_IDS)
def test_controls_compose_without_producing_an_invalid_config(vt):
    """Moving several controls at once is the normal case, and they interact."""
    import itertools
    P = _params_module(vt)
    keys = [c.key for c in getattr(P, "CONTROLS", ())][:3]
    if not keys:
        pytest.skip(f"{vt.slug} declares no controls")
    for combo in itertools.product([0.0, 0.5, 1.0], repeat=len(keys)):
        p = vt.default_params()
        for key, v in zip(keys, combo):
            P.apply_control(p, key, v)
        assert p.validate() == [], f"{vt.slug} {combo}: {p.validate()}"


@pytest.mark.parametrize("vt", TYPES, ids=TYPE_IDS)
def test_reconcile_is_idempotent(vt):
    import copy
    P = _params_module(vt)
    for c in getattr(P, "CONTROLS", ()):
        p = vt.default_params()
        P.apply_control(p, c.key, 1.0)
        P.reconcile(p)
        once = copy.deepcopy(p)
        P.reconcile(p)
        assert p == once, f"{vt.slug}: reconcile moved again after {c.key}"


@pytest.mark.parametrize("vt", TYPES, ids=TYPE_IDS)
def test_unknown_control_is_refused(vt):
    P = _params_module(vt)
    if not getattr(P, "CONTROLS", ()):
        pytest.skip(f"{vt.slug} declares no controls")
    with pytest.raises(KeyError):
        P.apply_control(vt.default_params(), "nonsense", 0.5)


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
