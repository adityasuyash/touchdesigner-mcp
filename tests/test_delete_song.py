"""Deleting a song, and letting TouchDesigner go of it.

Everything a song owns lives inside its folder -- `project.toe`, the separated
stems, the cue table, every render -- so trashing the folder is the whole
deletion. What is not in the folder is TouchDesigner's *memory*: it can still be
running the deleted project, and `provision` ends with `save_project`, so a
later run would write the song back onto disk.

The rule that shapes all of this: **deleting files must not depend on
TouchDesigner answering.** `select_song` used to block on it and a wedged TD
made a sidebar click hang for two minutes with no error. A delete that hangs
the same way would be worse, because the user has already committed to it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import lyricfield.ui.server as srv


class _TD:
    """A TouchDesigner that holds `folder`, or refuses to answer."""

    def __init__(self, folder: str | None = None, raises: bool = False):
        self.folder = folder
        self.raises = raises
        self.loaded: list[str] = []

    def run(self, code, timeout=None):
        if self.raises:
            raise TimeoutError("TouchDesigner did not respond")
        return f"{self.folder}/project.toe" if self.folder else ""


@pytest.fixture
def held(tmp_path, monkeypatch):
    """A song folder that has just been trashed, with TD still holding it."""
    gone = tmp_path / "sp4"
    gone.mkdir()
    return gone


def _use(monkeypatch, td, template: Path | None, loaded: list):
    monkeypatch.setattr(srv, "client", td)
    monkeypatch.setattr(srv.td_setup, "TEMPLATE", template or Path("/nope.toe"))
    monkeypatch.setattr(srv.sync, "load_project",
                        lambda c, p, **kw: loaded.append(str(p)))


# ------------------------------------------------- it lets go when it should

def test_touchdesigner_is_put_on_the_template(held, tmp_path, monkeypatch):
    """The point. A TD left running a deleted project can save it back."""
    template = tmp_path / "_template.toe"
    template.write_text("x")
    loaded: list[str] = []
    _use(monkeypatch, _TD(folder=str(held)), template, loaded)

    said = srv._release_td(held)
    assert loaded == [str(template)], "TouchDesigner was not handed the template"
    assert "let it go" in said


def test_a_different_song_is_left_alone(held, tmp_path, monkeypatch):
    """Deleting one song must not close another one you are working on."""
    template = tmp_path / "_template.toe"
    template.write_text("x")
    loaded: list[str] = []
    _use(monkeypatch, _TD(folder=str(tmp_path / "other")), template, loaded)

    said = srv._release_td(held)
    assert loaded == []
    assert "not holding it" in said


# ------------------------------------- and never waits on a TD that is stuck

def test_a_touchdesigner_that_will_not_answer_does_not_stop_the_delete(
        held, tmp_path, monkeypatch):
    """The rule. The files are already gone by the time this runs; a raise here
    would surface as a failed delete for work that actually succeeded."""
    loaded: list[str] = []
    _use(monkeypatch, _TD(raises=True), tmp_path / "_template.toe", loaded)

    said = srv._release_td(held)          # must not raise
    assert "could not reach" in said
    assert loaded == []


def test_the_answer_says_what_to_do_about_it(held, tmp_path, monkeypatch):
    """"It may still hold the old project" is the difference between being
    done and needing to restart before rendering."""
    loaded: list[str] = []
    _use(monkeypatch, _TD(raises=True), tmp_path / "_template.toe", loaded)
    assert "still hold" in srv._release_td(held)


def test_a_missing_template_is_reported_rather_than_raised(held, tmp_path,
                                                           monkeypatch):
    loaded: list[str] = []
    _use(monkeypatch, _TD(folder=str(held)), tmp_path / "gone.toe", loaded)
    said = srv._release_td(held)
    assert loaded == []
    assert "no template" in said


def test_a_load_that_fails_is_reported_rather_than_raised(held, tmp_path,
                                                          monkeypatch):
    template = tmp_path / "_template.toe"
    template.write_text("x")
    monkeypatch.setattr(srv, "client", _TD(folder=str(held)))
    monkeypatch.setattr(srv.td_setup, "TEMPLATE", template)

    def boom(c, p, **kw):
        raise RuntimeError("the template has no MCP server in it")

    monkeypatch.setattr(srv.sync, "load_project", boom)
    said = srv._release_td(held)
    assert "still holds" in said and "MCP server" in said


def test_touchdesigner_saying_nothing_is_not_taken_as_a_match(held, tmp_path,
                                                              monkeypatch):
    """An empty answer means "I do not know", not "I have the deleted one"."""
    loaded: list[str] = []
    _use(monkeypatch, _TD(folder=None), tmp_path / "_template.toe", loaded)
    srv._release_td(held)
    assert loaded == []


# ------------------------------------------------ what the folder holds

def test_a_song_keeps_everything_inside_its_own_folder():
    """Trashing the folder IS the deletion, which is only true while nothing a
    song owns lives outside it. A stem root moved elsewhere would leave
    hundreds of megabytes orphaned with nothing pointing at them."""
    from lyricfield.workspace import Workspace

    ws = Workspace("Scratch", Path("/tmp/lyricfield-test/scratch"))
    for name in ("project", "config_path", "cues_path", "drums_path",
                 "source_dir", "stems_dir", "exports_dir", "stills_dir"):
        p = getattr(ws, name)
        assert str(p).startswith(str(ws.dir)), f"{name} is outside the folder: {p}"
