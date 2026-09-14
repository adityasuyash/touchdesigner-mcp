"""Tests that close a whole class of defect rather than one instance.

Each of these would have caught a bug that actually shipped, and would go on
catching its successors. They are cheap, they need nothing installed, and they
are the highest-value tests in the suite.
"""

from __future__ import annotations

import ast
import collections
import re
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


# ------------------------------------------------- tunables nothing reads

TYPES_DIR = REPO / "lyricfield" / "types"


def _source_chain(slug: str, name: str, seen: set | None = None) -> str:
    """`<slug>/<name>.py`, plus whatever it delegates to.

    A type may reuse another type's builder -- both beatsync types construct
    `lyric_grid`'s network, because it is the same network -- so the value is
    consumed over there, and reading only the local file would report it as
    unread.
    """
    seen = set() if seen is None else seen
    if (slug, name) in seen:
        return ""
    seen.add((slug, name))
    path = TYPES_DIR / slug / f"{name}.py"
    if not path.exists():
        return ""
    src = path.read_text()
    for other in re.findall(rf"from \.\.(\w+)\.{name} import", src):
        src += _source_chain(other, name, seen)
    return src


@pytest.mark.parametrize("vt", TYPES, ids=TYPE_IDS)
def test_every_tunable_is_read_by_something(vt):
    """A value TouchDesigner ignores is worse than no knob at all.

    It reports success and changes nothing: the UI offers it, the config stores
    it, the push says it went in, and the render is identical. That was true of
    45 of the 51 values pushed before video types existed, and it came back the
    moment a second type reused the first one's sections -- both beatsync types
    inherited `letter_frac` and `dissolve`, which only a renderer with words can
    mean anything by.

    `field.py` reads what changes per frame, and reads it by the uppercased
    name; `build.py` bakes what belongs to the network, and reads it by the
    dataclass attribute.
    """
    field_src = _source_chain(vt.slug, "field")
    build_src = _source_chain(vt.slug, "build")
    params_src = _source_chain(vt.slug, "params")
    unread = []
    for name in _declared_fields(vt):
        # The field script binds each key as an uppercased module global. Do NOT
        # accept the lowercase quoted form here: every field-consumed tunable is
        # also a quoted key in that file's `DEFAULTS` mirror, so accepting it
        # meant adding a line to DEFAULTS satisfied this test whether or not
        # `onCook` ever read the value -- the rule CLAUDE.md leans on hardest,
        # weakest for exactly the change that needs it.
        if re.search(rf"\b{name.upper()}\b", field_src):
            continue
        # The builder reads it off the section, or emits it as a key. A bare
        # `\bname\b` was too loose: `mode`, `sat`, `level` and `glyphs` all
        # occur in build.py as TouchDesigner parameter names and locals, so four
        # genuinely unread tunables passed.
        if re.search(rf"\.{name}\b", build_src):
            continue
        if re.search(rf"""['"]{name}['"]""", build_src):
            continue
        # A section may consume its own tunable in a method -- `Analysis.scaled`
        # turns the raw gates into the ones the network is built with.
        if re.search(rf"\bself\.{name}\b", params_src):
            continue
        unread.append(name)
    assert not unread, (
        f"{vt.slug} declares tunables nothing reads: {unread}. "
        "Either consume them or stop offering them.")


# ------------------------------------------------- one flat namespace

def _track_fields():
    from dataclasses import fields as dc_fields
    from lyricfield.config import Track
    return {f.name for f in dc_fields(Track())}


@pytest.mark.parametrize("vt", TYPES, ids=TYPE_IDS)
def test_no_two_sections_share_a_tunable_name(vt):
    """Sections are an organising fiction; TouchDesigner sees one flat dict.

    `Config.as_params` calls `sections.flatten`, which drops the section names,
    so two sections sharing a key means one silently wins. `_declared_fields`
    itself is a dict keyed by bare name, which is why every other meta-test
    would stay green through such a collision -- it collapses there too.
    """
    seen, clashes = {}, []
    p = vt.default_params()
    for section in p.__dataclass_fields__:
        for name in vars(getattr(p, section)):
            if name in seen:
                clashes.append(f"{name} in both {seen[name]} and {section}")
            seen[name] = section
    assert not clashes, f"{vt.slug}: {clashes}"


@pytest.mark.parametrize("vt", TYPES, ids=TYPE_IDS)
def test_no_tunable_collides_with_a_measured_track_fact(vt):
    """`as_params` merges the track in last, so the track wins outright.

    This is not hypothetical. A `backdrop.level` of 0.05 -- deliberately below
    the dimmest word letter -- was silently replaced by `track.level`, the
    master's measured loudness at 0.42, which would have rendered the backdrop
    brighter than the words it sits behind. `validate()` could not see it: it
    inspects the dataclass and never the flat dict that TD is given.
    """
    from lyricfield.sections import flatten
    clash = sorted(set(flatten(vt.default_params())) & _track_fields())
    assert not clash, (
        f"{vt.slug} declares {clash}, which the track overwrites in as_params()")
