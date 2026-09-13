"""The repository itself: what a fresh clone gets.

Several files the code requires were sitting untracked, so `git clone` produced
a package that imported and then failed at runtime looking for a template or a
placeholder cue table. And the template that every new song is forked from
carried the 90-second timeline of the benchmark track, which is how one song's
play range came to cap every later song's renders.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _tracked() -> set[str]:
    out = subprocess.run(["git", "ls-files"], cwd=REPO,
                         capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    return set(out.stdout.split())


REQUIRED = [
    # the placeholder words style previews are rendered from, so a preview
    # carries no song's lyrics
    "lyricfield/data/preview_cues.tsv",
    # the project every new song is forked from, in its diffable text form
    "templates/_template.toe.toc",
    "templates/_template.toe.dir/local/time.parm",
    # the one shipped style, and the preview that makes it choosable
    "styles/lyric_grid/calm-drift/style.toml",
    # the package itself
    "lyricfield/run.py",
    "lyricfield/describe.py",
    "lyricfield/td_setup.py",
    "lyricfield/sections.py",
    "lyricfield/types/__init__.py",
    "lyricfield/types/lyric_grid/build.py",
    "lyricfield/types/lyric_grid/params.py",
    "lyricfield/types/lyric_grid/field.py",
]


@pytest.mark.parametrize("path", REQUIRED)
def test_a_fresh_clone_gets_everything_the_code_needs(path):
    assert path in _tracked(), f"{path} is required at runtime but not tracked"


def test_every_python_module_in_the_package_is_tracked():
    tracked = _tracked()
    missing = [str(p.relative_to(REPO)) for p in (REPO / "lyricfield").rglob("*.py")
               if "__pycache__" not in p.parts
               and str(p.relative_to(REPO)) not in tracked]
    assert not missing, f"untracked modules: {missing}"


def test_the_template_carries_no_songs_timeline():
    """It used to hold `end 5640 / rangeend 5433` -- the benchmark clip's 90
    seconds. Every song forked from it inherited a play range that silently
    discarded any seek past 1:30, so renders of longer songs looped and showed
    the wrong part of the track under correct audio.
    """
    parm = REPO / "templates" / "_template.toe.dir" / "local" / "time.parm"
    if not parm.exists():
        pytest.skip("no expanded template in the repo")
    values = {}
    for line in parm.read_text().splitlines():
        bits = line.split()
        if len(bits) >= 3 and bits[0] in ("end", "rangestart", "rangeend"):
            values[bits[0]] = float(bits[2])

    assert values.get("rangeend", 0) >= values.get("end", 0), \
        "the play range is shorter than the timeline; seeks past it are discarded"
    assert values.get("rangestart", 1) <= 1
    # Short and neutral: provisioning sets the real length per song. What must
    # not happen is the template carrying a particular song's shape.
    assert values.get("end", 0) <= 1200, \
        "the template has a song-sized timeline baked into it"


def test_the_control_ui_script_parses():
    """One typo in the UI's script leaves a blank page and no error anywhere.

    The whole interface is a single inline `<script>`; a syntax error in it
    stops every handler from being defined, so the page loads, renders its
    static markup and does nothing at all. That looks like a backend outage.
    Parsing it here catches it before it is served.
    """
    import json
    import shutil

    deno = shutil.which("deno")
    if not deno:
        pytest.skip("no JavaScript engine available to parse with")

    src = (REPO / "lyricfield" / "ui" / "static" / "index.html").read_text()
    blocks = re.findall(r"<script[^>]*>(.*?)</script>", src, re.S)
    assert blocks, "the control UI has no script at all"
    for i, body in enumerate(blocks):
        # `new Function` parses without running: no DOM is touched.
        probe = f"try {{ new Function({json.dumps(body)}) }} catch (e) {{ console.log(e.message); Deno.exit(1) }}"
        r = subprocess.run([deno, "eval", probe], capture_output=True, text=True)
        assert r.returncode == 0, f"script block {i} does not parse: {r.stdout.strip()}"
