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


def test_the_server_can_tell_its_own_source_has_changed():
    """A process cannot see that its imported modules are old. It can see that
    the files are newer than itself, and that check needs nothing fresh to work
    -- which is the point, because everything else in a stale process is stale.

    This is not theoretical: a server running from before `_prelude.py` existed
    pushed a field script that called a function the prelude was meant to
    define. TouchDesigner raised on every cook and the render waited thirty
    minutes before reporting a missing file.
    """
    from lyricfield.ui import server

    assert server.stale_sources(max_age=0.0) == [] or True   # whatever is true now
    before = server.STARTED
    try:
        server.STARTED = 0.0            # pretend this process is ancient
        stale = server.stale_sources(max_age=0.0)
        assert stale, "no package file looks newer than the epoch"
        assert any(p.startswith("lyricfield/") for p in stale)
    finally:
        server.STARTED = before


def test_a_run_is_refused_while_the_server_is_stale():
    """A run from stale code would push a mixture of this process's cached
    behaviour and whatever is on disk now — the exact combination that broke."""
    from fastapi import HTTPException

    from lyricfield.ui import server

    before = server.STARTED
    try:
        server.STARTED = 0.0
        server._stale_cache["at"] = 0.0
        with pytest.raises(HTTPException) as got:
            server.start_run(server.RunIn(name="anything"))
        assert got.value.status_code == 409
        detail = got.value.detail
        assert "changed" in detail["error"]
        assert "Restart" in detail["fix"]
    finally:
        server.STARTED = before
        server._stale_cache["at"] = 0.0


def test_an_api_refusal_becomes_something_a_person_can_see():
    """Every message the app produced went to `note()`, which writes into
    `#checks` — a div inside a collapsed <details> inside a container hidden
    until a song is selected. So pressing Make the video against a stale server
    did exactly what it was told, said so, and looked completely dead.

    Runs the page's whole script against a fake DOM and checks that a 409 with
    a structured detail arrives as a visible sentence carrying its remedy.
    """
    import json
    import shutil
    import subprocess

    deno = shutil.which("deno")
    if not deno:
        pytest.skip("no JavaScript engine available")

    src = (REPO / "lyricfield" / "ui" / "static" / "index.html").read_text()
    blocks = re.findall(r"<script[^>]*>(.*?)</script>", src, re.S)
    probe = r"""
class El {
  constructor(t){ this.tag=t; this.children=[]; this.style={}; this.dataset={};
    this.attrs={}; this.classList={add(){},remove(){},toggle(){}};
    this._text=""; this._html=""; this.hidden=false; this.className=""; this.value=""; }
  append(...k){ k.forEach(x=>this.children.push(x)); }
  prepend(x){ this.children.unshift(x); }
  setAttribute(k,v){ this.attrs[k]=v; }
  removeChild(){} remove(){} querySelector(){ return null; }
  querySelectorAll(){ return []; } addEventListener(){}
  set textContent(v){ this._text=v; } get textContent(){ return this._text; }
  set innerHTML(v){ this._html=v; if(v==="") this.children=[]; } get innerHTML(){ return this._html; }
  get lastChild(){ return this.children[this.children.length-1]; }
}
const nodes = {};
globalThis.document = { createElement: t => new El(t),
  querySelector: s => (nodes[s] ||= new El("div")), querySelectorAll: () => [],
  documentElement: { getAttribute(){return null;}, setAttribute(){} },
  addEventListener(){}, title: "" };
globalThis.window = { addEventListener(){}, matchMedia: () => ({matches:false}) };
globalThis.localStorage = { getItem(){return null;}, setItem(){} };
// Enough shape that init() does not reject; the test is about showErr, and an
// unhandled rejection would kill the process before it is reached.
globalThis.fetch = async () => ({ ok:true, status:200, json: async()=>({
  config:{track:{}}, sections:[], ranges:{}, controls:[], type:"lyric_grid",
  types:[], styles:[], songs:[], takes:[], cues:[], problems:[] }) });
globalThis.addEventListener = () => {};
globalThis.setInterval = () => 0; globalThis.setTimeout = () => 0;
const api = new Function(SRC + "\nreturn {showErr};")();
api.showErr(new Error(REFUSAL));
const h = nodes["#alerts"];
const said = h.children.map(c => c.textContent || "").join(" | ");
console.log(JSON.stringify({hidden: h.hidden, said}));
"""
    refusal = ('409 ' + json.dumps({
        "error": "the control server is running code from before 1 file changed",
        "fix": "press Restart to reload it, then run again"}))
    script = (f"const SRC = {json.dumps(chr(10).join(blocks))};\n"
              f"const REFUSAL = {json.dumps(refusal)};\n" + probe)
    r = subprocess.run([deno, "eval", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-800:]
    out = json.loads(r.stdout.strip().splitlines()[-1])
    assert out["hidden"] is False, "the refusal is still invisible"
    assert "running code from before" in out["said"], out["said"]
    assert "press Restart" in out["said"], "the remedy was dropped"


def test_the_look_controls_do_not_need_a_saved_song():
    """They describe the RENDERER, not the song, so hiding them until a song
    exists hides everything exactly when someone is setting one up.

    `#detailSections` used to unhide only when CURRENT_SLUG was set, which only
    happens on picking an existing song from the dropdown — so typing a new name
    left the whole panel invisible.
    """
    src = (REPO / "lyricfield" / "ui" / "static" / "index.html").read_text()
    ref = re.search(r"async function refreshAll\(\) \{(.+?)\n\}", src, re.S)
    assert ref, "refreshAll() is gone or was renamed"
    body = ref.group(1)
    assert "if (CURRENT_SLUG) { $('#detailSections').hidden = false;" not in body, \
        "the panel is gated on a saved song again"
    assert "$('#detailSections').hidden = false;" in body
    assert "needsSong(" in body, \
        "nothing tells the song-specific sections they have no song yet"
