"""Calibrating the container that was actually built.

`lyric_grid` places its glyphs by measurement rather than by algebra, because
the four numbers that do it are font metrics and `grid.font` is a parameter.
That solve used to be tied to whether anything had been pushed into
`/project1`, and to `/project1` itself by name -- so a build into a
sub-container never ran it.

`styles._scratch_network` is exactly that case: it builds a preview network into
`/project1/_preview` with `push=False`. Every preview of every grid renderer was
therefore recorded with the glyphs on the font's natural 39.6px pitch instead of
the cell's 53.3px.

It is not a subtle error once measured. The dim and lit *weights* come from the
Script TOP and land on the grid's rows; the glyphs land on the font's. For a
style whose words sit low in the frame the two never meet at all: Spotlight's
bold layer -- which IS the product of glyph and weight -- measured exactly zero
at every frame of a four-second capture, while both its inputs peaked at 1.0.

These tests pin the two halves of the fix: the solve is addressed to a
container, and a build into a sub-container neither skips it nor reaches out of
the box to do it.
"""

from __future__ import annotations

import inspect

import pytest

from lyricfield.config import Config
from lyricfield.types.lyric_grid import build as B

BOX = "/project1/_preview"


class _Client:
    """Records every path touched, and answers the probes with a lie.

    The lie is deliberate and harmless: the solve gives up early, which is all
    this needs. What is under test is *where* it looked, not whether it
    converged -- convergence is measured against TouchDesigner, not a stub.
    """

    def __init__(self):
        self.touched: list[str] = []
        self.code: list[str] = []

    def write(self, path, text):
        self.touched.append(path)

    def call(self, tool, **kw):
        if "path" in kw:
            self.touched.append(kw["path"])
        return {}

    def run(self, code, timeout=None):
        self.code.append(code)
        return "NONE"


def _paths_in(code: str) -> list[str]:
    """Operator paths a snippet of pushed Python mentions."""
    import re
    return re.findall(r"'(/project1[^']*)'", code)


# ------------------------------------------------------ addressed, not assumed

def test_the_solve_takes_the_container_it_is_to_calibrate():
    for fn in (B.calibrate_text, B._glyph_centre, B._text_geometry,
               B.apply_text_geometry, B._give_up):
        assert "container" in inspect.signature(fn).parameters, fn.__name__


def test_calibration_only_ever_touches_the_container_it_was_given():
    """The whole point. Probing writes a glyph into the character DAT and reads
    the Text TOP back -- aimed at `/project1` from a preview build, that would
    have written into the song."""
    c = _Client()
    B.calibrate_text(c, Config(type="lyric_grid"), container=BOX)
    outside = [p for p in c.touched if not p.startswith(BOX)]
    outside += [p for code in c.code for p in _paths_in(code)
                if not p.startswith(BOX)]
    assert not outside, f"calibration reached outside {BOX}: {sorted(set(outside))}"


def test_the_probe_writes_into_the_container_rather_than_the_song():
    c = _Client()
    B._glyph_centre(c, Config(type="lyric_grid"), (0, 0), 0.0, 0.0,
                    container=BOX)
    assert f"{BOX}/v7_chars_dim" in c.touched
    assert "/project1/v7_chars_dim" not in c.touched


def test_the_solved_geometry_goes_on_both_layers_of_that_container():
    """Both, because the lit layer used to be left where it was created and the
    bold words then sat on a different grid from the dim ones."""
    c = _Client()
    B.apply_text_geometry(c, 1.0, 2.0, 3.0, 4.0, container=BOX)
    assert sorted(c.touched) == [f"{BOX}/v7_text_dim", f"{BOX}/v7_text_lit"]


# ------------------------------------- every way out puts the network back

def _unbypassed(client) -> bool:
    return any("bypass = False" in c for c in client.code)


def test_a_solve_that_gives_up_unbypasses_the_script_top():
    """Probing needs the Script TOP bypassed, because it cooks ALWAYS and would
    rewrite the character DAT underneath the probe. Every exit therefore has to
    put it back -- and one did not.

    The early return for "probe glyphs did not render" returned a bare dict
    instead of going through `_give_up`, so the Script TOP stayed bypassed and
    the Text TOP kept the probe values. The field then drew nothing at all. It
    went unnoticed while calibration only ran during a push; the moment previews
    started calibrating, three styles recorded as pure black.
    """
    c = _Client()                       # every probe answers NONE
    res = B.calibrate_text(c, Config(type="lyric_grid"), container=BOX)
    assert res["ok"] is False
    assert _unbypassed(c), (
        "the solve gave up with the Script TOP still bypassed, which renders "
        "an empty frame")


def test_giving_up_restores_the_geometry_it_found():
    """Leaving `trackingx 0.1, linespacing 0` behind drops the row pitch from
    53px to the font's natural 40px, so the grid draws short and the bottom of
    every frame is empty -- with the build still reporting success."""
    c = _Client()
    B._give_up(c, {"tracking": -0.01, "spacing": 13.3, "posx": 1.0, "posy": 2.0},
               "no reason", container=BOX)
    assert sorted(c.touched) == [f"{BOX}/v7_text_dim", f"{BOX}/v7_text_lit"]
    assert _unbypassed(c)


class _Fake:
    """A TouchDesigner that lays glyphs out like the real one.

    Advance is `natural + k * tracking` per column and `natural + k * spacing`
    per row, positions shift the whole block, and -- the part that matters --
    a glyph outside the frame does not render, which is what `NONE` means.
    """

    ADV_X, ADV_Y = 30.05, 40.05
    K_X, K_Y = 1.0, 0.5

    def __init__(self, width=720, height=1280):
        self.w, self.h = width, height
        self.cell = None
        self.geo = {"trackingx": 0.0, "linespacing": 0.0,
                    "positionx": 0.0, "positiony": 0.0}
        self.code: list[str] = []
        self.touched: list[str] = []

    def write(self, path, text):
        self.touched.append(path)
        rows = text.split("\n")
        for r, row in enumerate(rows):
            c = row.find("#")
            if c >= 0:
                self.cell = (r, c)
                return

    def call(self, tool, **kw):
        if "path" in kw:
            self.touched.append(kw["path"])
        self.geo.update(kw.get("params") or {})
        return {}

    def run(self, code, timeout=None):
        self.code.append(code)
        if "numpyArray" not in code or self.cell is None:
            return ""
        r, c = self.cell
        x = (self.geo["positionx"] + 0.5 * self.ADV_X
             + c * (self.ADV_X + self.K_X * self.geo["trackingx"]))
        y = (-self.geo["positiony"] + 0.5 * self.ADV_Y
             + r * (self.ADV_Y + self.K_Y * self.geo["linespacing"]))
        if not (0 <= x < self.w and 0 <= y < self.h):
            return "NONE"
        return repr((float(x), float(y)))


@pytest.mark.parametrize("cols", [18, 24, 28, 32, 36])
def test_a_grid_too_wide_for_its_frame_is_still_measurable(cols):
    """At the natural advance, 32 columns of a 50px font want about 960px of a
    720px frame, so a corner probe simply does not render -- and the solve gave
    up, leaving the Script TOP bypassed and the probe values behind, which is a
    black frame. Three shipped styles are wider than 24 columns.
    """
    cfg = Config(type="lyric_grid")
    cfg.params.grid.cols = cols
    c = _Fake(cfg.params.grid.width, cfg.params.grid.height)
    res = B.calibrate_text(c, cfg, container=BOX)
    assert res["ok"], res
    # The solve has to actually land the glyphs on the cells it was given.
    cell_w = cfg.params.grid.width / cols
    assert abs(res["residual_far"][0]) < cell_w / 3.0, res


def test_the_solve_puts_the_glyphs_on_their_cells(): 
    """What calibration is for, end to end against the fake."""
    cfg = Config(type="lyric_grid")
    c = _Fake()
    res = B.calibrate_text(c, cfg, container=BOX)
    assert res["ok"], res
    assert abs(res["residual_near"][0]) < 1.0
    assert abs(res["residual_near"][1]) < 1.0


# ------------------------------------------------- and the build still runs it

@pytest.fixture
def quiet_build(monkeypatch):
    """`build` with everything but the calibration decision stubbed out.

    What is under test is one branch, not the builder engine -- which has its
    own coverage and needs a real TouchDesigner to mean anything.
    """
    from lyricfield import sync as sync_mod

    calls: list[dict] = []
    monkeypatch.setattr(sync_mod, "quiesce", lambda c: None)
    monkeypatch.setattr(sync_mod, "resume", lambda c: None)
    monkeypatch.setattr(sync_mod, "push_field", lambda c, cfg: None)
    monkeypatch.setattr(sync_mod, "push_params", lambda c, cfg: None)
    monkeypatch.setattr(B, "check_types", lambda c, specs: [])
    monkeypatch.setattr(B, "create_ops", lambda c, s, say, box: [])
    monkeypatch.setattr(B, "drop_autocreated", lambda c, s, say, box: None)
    monkeypatch.setattr(B, "load_analysis_component",
                        lambda c, cfg, say, box: "")
    monkeypatch.setattr(B, "wire_ops", lambda c, s, say, box: [])
    monkeypatch.setattr(B, "apply_exprs", lambda c, s, say, box: [])
    monkeypatch.setattr(B, "verify", lambda c, cfg, box: [])

    def _cal(client, cfg, progress=None, container=B.ROOT):
        calls.append({"container": container})
        return {"ok": True}

    monkeypatch.setattr(B, "calibrate_text", _cal)
    return calls


def test_a_build_that_does_not_push_still_calibrates(quiet_build):
    """The regression itself. `calibrate` hung off `push`, and the preview path
    passes `push=False`, so the solve was skipped for every preview ever
    recorded."""
    B.build(_Client(), Config(type="lyric_grid"), container=BOX, push=False)
    assert quiet_build, "a build with push=False did not calibrate"


def test_the_build_hands_its_own_container_to_the_solve(quiet_build):
    B.build(_Client(), Config(type="lyric_grid"), container=BOX, push=False)
    assert quiet_build[0]["container"] == BOX


def test_calibration_can_still_be_turned_off(quiet_build):
    """`calibrate=False` is how the builder's own tests avoid a solve that
    needs a real Text TOP to answer."""
    B.build(_Client(), Config(type="lyric_grid"), container=BOX, push=False,
            calibrate=False)
    assert not quiet_build


def test_a_failed_solve_is_reported_as_a_build_problem(monkeypatch, quiet_build):
    """Carrying on silently is what left the row pitch at the font's natural
    advance with the build still reporting success."""
    monkeypatch.setattr(B, "calibrate_text",
                        lambda c, cfg, progress=None, container=B.ROOT: {
                            "ok": False, "error": "did not converge"})
    res = B.build(_Client(), Config(type="lyric_grid"), container=BOX,
                  push=False)
    assert any("calibration failed" in p for p in res["problems"]), res


@pytest.mark.parametrize("name", ["v7_text_dim", "v7_text_lit"])
def test_the_text_tops_the_solve_writes_are_the_ones_the_network_creates(name):
    """A typo here would fail silently -- `set` on a missing operator is not an
    error the calibration would notice."""
    specs = B.network(Config(type="lyric_grid"))
    assert any(s.name == name for s in specs), name
