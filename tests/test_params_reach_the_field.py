"""Whether a renderer can read the parameters it is handed.

There were two ways of writing the params DAT and two ways of reading it, and
they did not match up. `lyricfield.sync` writes a Python module (`P = {...}`);
the three grid renderers read it back through `mod()`; the eight renderers
written since parsed the DAT's text as JSON; and `styles.capture_preview` wrote
JSON. So a grid renderer previewed on the defaults compiled into its field
script, and a new renderer *rendered* on them -- in both cases silently, because
a field script that cannot read its params does not fail. It draws something
plausible.

Measured at the time: a plain `lyric_grid` capture and a backdrop one came back
byte-identical, and seven backdrop previews in the gallery were the same video.

These tests ask the only question that closes the class: does every renderer
receive what every writer sends?
"""

from __future__ import annotations

import json
import types as pytypes

import numpy as np
import pytest

from lyricfield import sync
from lyricfield import types as types_mod
from lyricfield.config import Config

TYPES = [t for t in types_mod.list_types() if t.field_source()]
IDS = [t.slug for t in TYPES]


class _FakeDAT:
    def __init__(self, text=""):
        self.text = text
        self.numRows = 0

    def __getitem__(self, rc):
        raise IndexError(rc)


def _field(vt, params_text):
    """The renderer's field script, loaded with a params DAT holding this text.

    `mod(name)` is TouchDesigner's way of importing a Text DAT as a module, so
    the fake executes the text the same way TD would and exposes its globals.
    """
    src = vt.field_source()
    mod_obj = pytypes.ModuleType(f"{vt.slug}_params_under_test")
    mod_obj.__dict__["np"] = np
    dats = {"params": _FakeDAT(params_text)}

    def _op(name):
        return dats.get(name)

    def _mod(name):
        d = dats.get(name)
        if d is None:
            raise NameError(name)
        m = pytypes.ModuleType("dat")
        exec(compile(d.text, f"{name}.py", "exec"), m.__dict__)
        return m

    mod_obj.__dict__["op"] = _op
    mod_obj.__dict__["mod"] = _mod
    mod_obj.__dict__["root"] = pytypes.SimpleNamespace(
        time=pytypes.SimpleNamespace(seconds=0.0, end=3600.0, rate=60.0))
    exec(compile(src, "field.py", "exec"), mod_obj.__dict__)
    mod_obj.__dict__["_apply_params"]()
    return mod_obj


def _a_changed_look(vt) -> tuple[Config, str, object]:
    """A config of this type with one tunable moved off its default.

    The value has to differ from the field script's own fallback, or "the
    params arrived" and "the params were ignored" look identical.
    """
    cfg = Config(type=vt.slug)
    flat = cfg.as_params()
    src = vt.field_source()
    mod_obj = pytypes.ModuleType("probe")
    mod_obj.__dict__["np"] = np
    mod_obj.__dict__["op"] = lambda name: None
    mod_obj.__dict__["mod"] = lambda name: (_ for _ in ()).throw(NameError(name))
    mod_obj.__dict__["root"] = pytypes.SimpleNamespace(
        time=pytypes.SimpleNamespace(seconds=0.0, end=3600.0, rate=60.0))
    exec(compile(src, "field.py", "exec"), mod_obj.__dict__)
    defaults = mod_obj.__dict__["DEFAULTS"]
    for key, fallback in defaults.items():
        if key not in flat or not isinstance(fallback, (int, float)):
            continue
        if isinstance(fallback, bool):
            continue
        want = round(float(fallback) + 1.0, 4)
        flat[key] = want
        return flat, key, want
    pytest.skip(f"{vt.slug} has no numeric tunable to move")


@pytest.mark.parametrize("vt", TYPES, ids=IDS)
def test_a_renderer_reads_the_params_sync_writes(vt):
    """The format every real render is handed."""
    flat, key, want = _a_changed_look(vt)
    text = sync.params_text(_CfgWith(vt.slug, flat))
    mod_obj = _field(vt, text)
    assert mod_obj.__dict__["PARAMS_MISSING"] is False, (
        f"{vt.slug} could not read what sync.params_text wrote")
    assert mod_obj.__dict__[key.upper()] == pytest.approx(want)


@pytest.mark.parametrize("vt", TYPES, ids=IDS)
def test_a_renderer_reads_the_params_a_preview_writes(vt):
    """JSON, which is what a capture used to write and what eight of the
    renderers were built to read. Accepted too, so that a params DAT already
    inside somebody's .toe keeps working after this change."""
    flat, key, want = _a_changed_look(vt)
    mod_obj = _field(vt, json.dumps(flat))
    assert mod_obj.__dict__["PARAMS_MISSING"] is False, (
        f"{vt.slug} could not read a JSON params DAT")
    assert mod_obj.__dict__[key.upper()] == pytest.approx(want)


@pytest.mark.parametrize("vt", TYPES, ids=IDS)
def test_a_renderer_says_so_when_it_has_no_params_to_read(vt):
    """The flag the preflight check and the preview capture both ask for. It
    has to be true when the DAT is empty, or neither can tell the difference
    between a look and a set of defaults."""
    mod_obj = _field(vt, "")
    assert mod_obj.__dict__["PARAMS_MISSING"] is True


class _CfgWith:
    """A stand-in for Config that hands `sync.params_text` a chosen flat dict."""

    def __init__(self, slug, flat):
        self.type = slug
        self._flat = flat

    def as_params(self):
        return self._flat
