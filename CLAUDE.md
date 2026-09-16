# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A generic MCP server (`scripts/td_mcp_server.py`) that runs inside TouchDesigner via a Web Server DAT on port 9988. It implements MCP Streamable HTTP (JSON-RPC over POST to `/mcp`) with no external dependencies beyond TD itself.

## Development Workflow

After modifying `scripts/td_mcp_server.py`, reload into TD and rebuild the `.tox`:

```
td_run: exec(open(project.folder + '/scripts/rebuild_tox.py').read())
```

This syncs the script into the handler DAT and re-exports `td_mcp_server.tox`. The MCP client may need a reconnect (`/mcp`) to pick up new tools.

## Architecture

Single-file server (`scripts/td_mcp_server.py`) attached to a Web Server DAT. The entry point is `onHTTPRequest()` which routes to `_handle_request()` → `_handle_one()` → individual `handle_*` functions via `TOOL_HANDLERS` dispatch dict.

Key subsystems:
- **Tool definitions**: `TOOLS` list (JSON Schema) at top of file, handlers named `handle_<tool_name>`
- **Frame capture**: Synchronous capture via `_capture_frame()` — advances the timeline and force-cooks the operator chain each frame. Used by the `observe` tool.
- **APNG encoder**: `_encode_apng()` — pure Python animated PNG encoder (no PIL/ffmpeg needed)
- **Root discovery**: `_get_root()` uses `me.parent()` so the server works regardless of where it's placed in the operator hierarchy

## Tools (13)

`run`, `inspect`, `set`, `create`, `wire`, `observe`, `render`, `read`, `write`, `edit`, `list`, `docs`, `map`

**Use `docs` before creating operators** to look up correct parameter names, menu values, and type constants. TD parameter names are often abbreviated (e.g. `rough` not `roughness`, `wavetype` not `type`, `frequency` not `freq`). Use `docs` with `type='list_types'` to find type constants like `lfoCHOP`, `noiseTOP`, etc.

**Use `map` before creating operators** to see the current network layout with `@(x,y)` coordinates, then place new operators nearby using the required `nodeX`/`nodeY` params on `create`.

### Adding a new tool

1. Add its JSON Schema to the `TOOLS` list
2. Write a `handle_<name>(args)` function
3. Add it to `TOOL_HANDLERS` dict
4. Update tool counts/lists in: this file, `../CLAUDE.md`, `README.md`

## Project Files

- `scripts/td_mcp_server.py` — the MCP server source (synced to a TextDAT in TD)
- `scripts/rebuild_tox.py` — reloads server script into TD and re-exports the `.tox`
- `td_mcp_server.tox` — pre-wired component (Web Server DAT + callback script), drag-and-drop install
- `.mcp.json` — Claude Code MCP client config pointing to `localhost:9988/mcp`

## Working with TouchDesigner

- Operator paths are absolute (e.g. `/project1/out`). The root container is auto-discovered via `me.parent()`.
- `.toe` files are binary — can't be diffed or merged. All `.toe` files are gitignored.
- TD's Python environment is embedded (no pip). Only stdlib + numpy are available.
- To set expressions on parameters, use `par.name.expr = "..."` — assigning a string directly to a numeric par will error.
- After writing a GLSL shader, call `op.par.loaduniformnames.pulse()` to auto-detect uniforms.

## lyricfield — the music-video system

A second project lives in `lyricfield/`. It uses this MCP server as transport but
is otherwise independent: ingest a song, pick a **video type**, render it.

Ingest is shared by every type — separate, analyse, transcribe — and yields one
substrate (duration, kick entry, hi-hat entry, beat grid, silence windows,
word-level cues). What differs is the renderer.

**The repo is the source of truth.** TD holds a thin shell (a Script TOP, cue and
character DATs, the render chain); `lyricfield/sync.py` pushes behaviour in. Edit
`lyricfield/types/<slug>/field.py` here — never in the DAT, or the next push
overwrites it.

```
lyricfield/
  config.py      a song: track facts + video type + that type's params
  sections.py    the sectioned-dataclass/TOML machinery those share
  cues.py        per-word cue table, TSV, hand-editable
  beat.py        what a drum does to the WORDS: the effect presets
  compose.py     the word container, and the beat-response chain after it
  fx_drive.py    that chain's driver, pushed into TD like a field script
  separate.py    Demucs stem separation (shells out to the CLI)
  transcribe.py  Groq Whisper -> word-level cues
  analysis.py    silences, kick entry, tempo, beat phase
  pipeline.py    prepare(): separate -> analyse -> transcribe, resumable
  styles.py      named presets of one type's params + video previews
  workspace.py   one folder per song
  td_client.py   JSON-RPC client for :9988
  sync.py        push repo -> TD, pull cue tables out
  render.py      capture, container validation, stem muxing, stills
  ui/            control UI (python -m lyricfield.ui.server -> :8765)
  preflight.py   assert what a render leans on, and repair it
  types/         the video types, one package each
    _build.py    the builder engine: OpSpec and the create/wire/verify helpers
    _controls.py the named-control machinery every type binds to its own knobs
    _prelude.py  prepended to every field script (drum onsets, edge detection)
    lyric_grid/  the song's words in a character field
    monument/    one word, filling the frame
    window/      the words cut out of moving light
    orbit/       the line riding a parametric curve
    swarm/       words that fly in and are knocked apart
    horizon/     a neon grid to a banded sun
    longhand/    the lyrics lettered by hand, big, over your footage
    glitch/      the words torn, split and scanlined
docs/
  visual-references.md   the looks these were built from, and what is out of reach
tests/           pytest; `python -m pytest` with TouchDesigner shut
```

Run the UI and work from there; every stage also has a CLI entry point.

### Tests

`pip install -r requirements-dev.txt && python -m pytest`. The default run needs
no TouchDesigner and no network; tests that need ffmpeg are marked and skipped
when it is absent. Media fixtures are synthesised by ffmpeg rather than checked
in, because a generated fixture has a ground truth a real recording cannot give:
a 120 BPM click train must measure 120, black must read 16.0 in limited-range
luma, and a video that flashes at known times must correlate with those and not
with others.

The meta-tests in `tests/test_meta.py` are the ones worth keeping green above
all: they close whole classes -- every tunable bounded, every control target in
range, no module defining the same top-level name twice -- rather than one
instance each. Two live bugs were found by writing them.

### Adding a video type

1. `lyricfield/types/<slug>/params.py` — the tunables as a sectioned dataclass
   with `validate()`
2. `lyricfield/types/<slug>/field.py` — code that runs inside TD, if it needs any
3. `lyricfield/types/<slug>/build.py` — construct the network from an empty
   project. **Required**: provisioning forks a template whose only operator is
   the MCP server, so a type with no builder gets an empty project and the
   first push fails. Borrow the engine from `types/_build.py`; do **not**
   import another type's `build` or its `Grid` — those two imports are the
   entire reason three renderers drew one picture.
4. `lyricfield/types/<slug>/__init__.py` — `TYPE = VideoType(...)`

**Every tunable a type declares must be consumed by its `field.py` or its
`build.py`.** Pushing a value TD ignores is worse than not having the knob: it
reports success and changes nothing. That was true of 45 of the 51 values pushed
before types existed. The split is: `field.py` reads what changes per frame;
`build.py` bakes what belongs to the network (font, resolution, the glow and
bloom expressions).

**Read the params DAT through the prelude's `_read_params`, never by hand.**
There were two writers and two readers of that one DAT and they did not match
up: `sync.params_text` writes a Python module (`P = {...}`), the three grid
renderers read it back through `mod()`, the eight renderers written since parsed
the text as JSON, and `styles.capture_preview` wrote JSON. Nothing failed — a
field script that cannot read its params falls back to the defaults compiled
into it and draws a plausible picture, so the new renderers rendered on defaults
and the grid renderers previewed on them. Seven backdrop previews in the gallery
were byte-identical recordings of `lyric_grid`'s defaults. `preflight` now asks
the running script whether it read them (`sync.params_were_read`), and a capture
that cannot is refused as `FallbackPreview` rather than shipped.

### Building a renderer that is not the character grid

Nine of the eleven types were written after the grid, and every one of these
cost real time to discover. None is findable from the Python side.

- **A Text TOP draws its own inline `text` and ignores its DAT** while that
  string is non-empty. It ships holding the word "derivative", so the first
  render of a new type is that word at whatever size your code computed for the
  real one. Set `text` to `""`.
- **Font size is in POINTS by default.** `fontsizexunit`/`fontsizeyunit` must be
  set to `pixels`, and so must `positionunit`, or every size and place you
  compute from the frame follows the display's DPI. This is the same defect that
  once made a grid's row pitch depend on the monitor it was built on.
- **Ask TouchDesigner for parameter names; do not infer them.** A Level TOP has
  no `extendleft` (it has `fillmode`); a Text TOP has no `bordera` (it has
  `borderar`, `borderag`, ...). `docs`, or `[p.name for p in o.pars()]`, answers
  in seconds.
- **A curve written in 0..1 coordinates is an ellipse on screen.** A step in x
  covers `width` pixels and a step in y covers `height`. Scale against the
  smaller side. This was got wrong twice in one afternoon -- a sun and a circle.
- **A blur conserves energy.** Spreading a one-pixel filament over four pixels
  divides its brightness by about fifty; a line renderer needs a gain stage
  after the tight blur, and a second wider blur for the halo. One blur gives
  either a hard line with no bloom or a smear with no line.
- **The Text TOP's Specification DAT** takes a table of `x`, `y`, `text` and
  places each row at its own pixel coordinate, origin **lower-left**. That is
  how a renderer escapes a lattice; there is no other way to place glyphs
  freely without instancing, which is unsupported on some Macs.
- **Clamp every decay envelope at BOTH ends.** `1 - (t - struck) / decay` is
  greater than one whenever the strike is ahead of the playhead, which a seek
  makes routine, and it grows without limit. Measured: a field's mean at 0.86 of
  white with everything else invisible inside it.
- **Prefer a frame that is a pure function of its own timestamp.** Feedback
  TOPs, the Particle SOP and the Bullet solver all step per cook, so a dropped
  frame or a seek changes what they produce and a song does not render the same
  way twice. A trail drawn from the curve's own past, or a spring re-integrated
  from the line's start, costs almost nothing and re-renders exactly.
- **Whole-array or nothing.** 720x1280 is a million pixels a frame; a per-pixel
  Python loop is not an option. Precompute the coordinate grids once.
- **A Text TOP has ONE font size for its whole Specification DAT.** Per-letter
  scale is therefore not available inside one, which is why `longhand` draws
  its lettering through one Text TOP per size step and assigns each letter to
  one. The sizes come from `params.hand_sizes` and both halves read that one
  list: if the size `build.py` bakes in drifted from the size `field.py` laid
  the row out at, the row would not close up.
- **Bottom-align a Text TOP when rows of different sizes share a line.** With
  `aligny` at centre a taller letter rides up and the line reads as bouncing;
  at bottom a row's y IS its baseline and sizes line up for free.
- **A Remap TOP moves the pixels that are there**; input1 is the picture,
  input2 the map, and `horzsource`/`vertsource` say which channel carries which
  coordinate. It is how `glitch` tears. Drawing displaced rectangles instead
  looks like rectangles.
- **A Reorder TOP takes FOUR inputs**, so a three-way channel split is one
  operator rather than a tree of them.
- **A composite `add` CLAMPS at white on an 8-bit TOP.** So "sum N copies and
  scale by 1/N" is not an average: three taps of a 0.93 layer summed to exactly
  1.0 and the Level after them turned that into 0.333, which made a whole
  renderer grey at a peak of 0.59 while every slab read 0.9294 one operator
  upstream. Scale each input BEFORE the sum.
- **A map that is linear in x can be computed eight pixels wide.** Interpolating
  it back up to frame width is then exact, not approximate -- `glitch`'s tear
  field is a per-row displacement, so a full-resolution map would be a million
  floats a frame for no difference at all.

### The beat is an effect, not a picture

Seven renderers were once built on the premise that a beat look is a *picture*
-- rings, bars, a dot screen -- to put behind the words, first by folding it
into `lyric_grid`'s own grid and then by compositing two networks. That premise
was wrong and all of it is gone. The beat is visible **in the text**: the type
punches on the kick, its glow swells, it jolts, its channels pull apart.

So there is one chain after the word renderer, and a preset is a set of numbers
(`beat.py`) rather than a renderer. Nothing in the chain knows which renderer
drew the frame it is moving, which is what makes every effect work with every
word look for free.

**Floaty, moving, organic is the envelope, not the structure.** A linear
`1 - age/decay` reads as a meter. `beat.impulse` is a damped spring: a 40ms
eased attack, then a release that falls, *crosses* its rest point, swings about
13% under and settles. That crossing is the difference between type that reads
as struck and type that reads as faded. `beat.drift` keeps the layer moving
between hits from three incommensurable sines -- at 5.6/8.8/17s, because a first
draft at 20-70s was a one-way ramp over a four-second preview, and slow enough
to be invisible is the same as not being there.

`fx_drive.py` cannot import `beat.py` -- it is pushed as one DAT -- so the
envelope exists twice, and a test walks both and asserts they agree to 1e-9.

**A direction must not double as a magnitude.** The jolt multiplied its
amplitude by `drift()` itself, a wander in -1..1 whose mean absolute value is
0.39, so a 32px knock landed as about 6 and Jolt read as a dimmer Punch.
`beat.shake_offset` normalises the direction, and renormalises again after the
tilt weighting, so `shake.amount` is the peak displacement it says it is.

### Reading a visual reference

**Watch it. Do not read about it, and do not stop at stills.** The
Chainsmokers' "Closer" was rebuilt three times from written descriptions -- one
of them the user's own -- and a fourth time from four still frames, which fixed
the look and missed the motion entirely. A still cannot show motion, and the
motion was the whole complaint: "the words just appear on screen".

`yt-dlp` the video and tile it. `fps=8,scale=300:-1,tile=5x4` through one
transition shows in one image what a dozen stills cannot, and tracking the
bright pixels' centroid frame to frame turns "it drifts" into a number.
`docs/visual-references.md` records what each reference actually shows, the
measurements, and the readings that turned out to be wrong.

### A Script TOP with no outputs never runs

`CookLevel.ALWAYS` says how OFTEN an operator cooks when something asks for it,
not whether anything asks. `fx_drive` was built as "not the picture" -- sixteen
pixels whose whole job is to set parameters on its siblings -- and with nothing
downstream it sat outside the cook chain and never ran: a render with a beat
preset picked came out identical to one with none, while the params, the chain
and a 963-row drum table beside it were all correct. Make the driver's pixels
part of the picture, as `monument`'s ground is; a tap that changes nothing
fixes the cook and invites the next reader to delete it. `test_meta` refuses a
Script TOP that nothing consumes.

### What a preset preview has to be

The row of beat tiles is read ACROSS, so everything that is not the effect has
to be held still. Getting this wrong produced three rounds of "they all look
the same", and none of the causes was the effect itself:

- **The reference renderer must do nothing on the beat.** `monument` lifts the
  whole frame by `kick_lift` on every kick; that is its own response, it is
  identical in all five tiles, and it was the loudest thing in each -- the
  `none` tile, which shows no effect at all, went from a frame mean of 7.6 to
  16.1 four times in four seconds. `beat.reference_params` switches it off.
  A new reference has to be checked the same way.
- **One word, held.** `data/preview_beat_cues.tsv` is one cue plus a sentinel:
  a renderer holds a word until the NEXT cue lands, so a lone cue fades out
  before the first kick. Running words meant the effect competed with eight
  transitions in four seconds.
- **One kind of motion per preset, all on the same drum.** Every preset used to
  carry bloom, which is light, so the row was one effect at four strengths.
  And the shake and the tear fired on the snare while the brightest moment was
  the kick, so at the instant the eye is drawn to there was nothing to tell the
  tiles apart.
- **Measure the baseline, not just the presets.** Every other check compares a
  preset against the baseline, so anything the baseline does cancels out and is
  invisible to all of them. That is how a flashing reference survived twice.

**A preview must not inherit the song's structure.** `capture_preview` copied
`kick_in`, `high_in` and the measured silences from whatever song was loaded,
and every renderer dims itself before the drums enter. Measured live: a song
whose kick enters at 61.2s, previewed at 3.55s, gave a section gain of 0.35 and
`mon_now_l.brightness1` of 0.308 -- every preview of every renderer recorded at
a third of its brightness, with a silence window able to blank the words
outright. The song still supplies the audio and the beat; the arc is
neutralised.

**`Config.response`, not `Config.beat`.** Every renderer already has a `[beat]`
section of its own -- what the drums do *inside* its picture -- and `Config`
flattens sections into one namespace. Two things named `beat` keep whichever
came last.

### Concepts

- **Workspace** — one folder per song under `~/lyricfield-projects/<slug>/`:
  `project.toe`, `config.toml`, `cues.tsv`, `source/`, `stems/`, `exports/`.
  A new song's `.toe` is forked from `_template.toe`, a project whose only
  operator is the MCP server -- `project.load()` kills the server if the target
  does not contain one. No full template is checked in (binary, undiffable,
  stale within a day).
- **Video type** — the renderer: its TD network, its tunables, whether it needs
  lyrics. Ingest is shared; this is what differs. `lyricfield/types/<slug>/`.
- **Style** — a named preset of one type's params, so it is reusable across songs
  and provably cannot touch song data. Scoped to its type, because `lyric_grid`'s
  sections mean nothing to another renderer; applying across types is refused.
  Stored in `styles/<type>/<slug>/` (tracked) with a short video preview, because
  motion is what distinguishes a style and a still cannot show it. The previews
  themselves are gitignored — they are renders of whichever song was loaded.

### TouchDesigner client gotchas

These are the ones that cost real time. All are handled in `td_client.py`; do not
re-introduce them by calling the raw tools.

- **The server reports failure *inside* the payload.** `write` on a DAT this
  session has not `read` returns `{"error": ...}` with no `isError` flag. Missed,
  this makes every push a silent no-op that reports success. `TDClient.write`
  reads first; `TDClient.call` raises on an in-payload error.
- **`run` returns two shapes.** Printed output lands in `"output"`, a bare
  expression in `"result"`. Reading only one silently yields empty strings.
- **`read` is for display, not parsing.** It prefixes every line with its number,
  which shifts every column. Use `TDClient.dat_text` to consume a DAT.
- **Wrap multi-statement `run` code in a function.** The exec scope gives
  module-level names no visibility inside nested defs or comprehensions.
- **Never scrub the timeline backwards mid-measurement** — the field script resets
  its layout on a backward jump, so samples come back empty and look like a bug.
- **Look up TD parameter names with `docs`.** `amp` not `amplitude`, `rough` not
  `roughness`, `size` not `radius`.
- **`map` reports a stale expression as if it were active.** It reads `p.expr`
  without checking `p.mode`, so a parameter switched back to a constant still
  shows its old expression. Confirm with `p.eval()` before believing it.
- **`project.load()` kills the MCP server** — it lives inside the project. It
  only comes back if the project being loaded contains one, so never point a
  load at a file you have not checked, and always follow it with
  `TDClient.wait_until_ready()`. `lyricfield/td_setup.py` keeps a template whose
  only operator is the server, for exactly this.

### Rendering and verification

- **Check the picture against the cue table, not just its brightness.** A
  30-second render of entirely the wrong part of the song was written out
  "verified with no problems": every regional brightness check passed, because
  they were good frames of the wrong thing. `render.picture_matches_cues` counts
  bright pixels inside a word's plateau against those between words — the
  failing render measured *more* light between words than during them (ratio
  0.49, against 10-40 when it is right).
- **Verify at `/project1/out`, never upstream.** A bloom branch went negative (a
  Level TOP black level remaps, it does not clamp) and subtracted ~0.23 from the
  whole frame while every upstream metric looked perfect.
- **Brightness stacks.** Spark/ripple lifts add on top of the glow; 0.75/0.40
  measured 0.99 at the output. Only a cued word may reach 1.0.
- **The band must fill the frame.** `band` rows inside `vrows` — leaving band at
  14 of 24 put 480px of dead black at the bottom for three versions.
- **TD's render audio drifts** (wall-clock recording, slower-than-realtime
  cooking). Always discard it and mux the stems with ffmpeg.
- **TD reports renders finished early**, while the moov atom is still being
  written. Require a stable size *and* a successful ffprobe parse.
- **Quiesce before saving.** The Script TOP is `CookLevel.ALWAYS` and blocks the
  web server; saves hang for 1-3 minutes and then succeed.
- **The timeline has two lengths, and `end` is the one that does not matter.**
  `rangestart`/`rangeend` with `rangelimit` at "loop" confine the playhead, and
  nothing errors when you try to leave that range: `me.time.frame += 100` moves,
  `me.time.frame = <past rangeend>` silently snaps back. A `rangeend` inherited
  from a 90s song capped a 264s track, so seeking to 2:45 wrapped round to 1:20
  and rendered the wrong part of the song with words that did not match the
  moment. `sync.set_timeline_length` sets both; never set `end` alone.
- **A seek must be read back.** `park()` asks for a frame and then checks where
  the playhead actually is, because the write above fails silently. Nothing
  downstream should assume a seek worked.
- **Text calibration needs the Script TOP bypassed, and must restore on
  failure.** `calibrate_text` writes a probe glyph into the character DAT and
  measures where it lands; the Script TOP cooks ALWAYS and rewrites that DAT, so
  with it live the probes are garbage and the solve gives up. It used to give up
  *leaving the probe values behind* — `trackingx 0.1, linespacing 0` — which
  drops the row pitch from 53px to the font's natural 40px, so the grid draws
  short and the bottom third of every frame is empty, with the build still
  reporting success. It now bypasses the Script TOP itself, applies the solved
  geometry to **both** text layers, puts the old geometry back if it fails, and
  reports failure as a build problem.
- **Calibration belongs to the container, not to the push.** `calibrate_text`
  solves the four glyph-placement numbers by measurement; it used to be called
  only when `push` was true and to address `/project1` by name. `styles.
  _scratch_network` builds a preview with `push=False`, so the solve never ran
  there and every preview of a grid renderer drew its glyphs on the font's
  natural 39.6px pitch while the weights that light them sat on the grid's
  53.3px. The two never met for a style whose words sit low in the frame:
  Spotlight's bold layer measured exactly zero at every frame of a capture while
  both its inputs peaked at 1.0. Both halves are now addressed by container.
- **A TOP inside a base COMP cannot be wired to one outside it**, and a COMP is
  not a valid TOP input either. Worse, the `wire` tool reports SUCCESS for the
  first and leaves the input unconnected -- measured, a live layer at 0.31
  arriving through a Level TOP as 0.0 with nothing reporting a fault. A Select
  TOP pulls a TOP by path across the boundary and is the idiomatic answer.
- **`over` does nothing over an opaque frame.** Every renderer here draws its
  own black ground, so its output is fully opaque and an `over` composite hides
  whatever is under it completely. `add` stacks, which is the brightness defect
  this project has fixed three times. `maximum` is usually what is wanted.
- **`.module` on a DAT compiles it, so it RAISES rather than returning None.**
  `reset_field_state` died on a container whose callbacks DAT was empty --
  exactly the state a run that crashed before pushing leaves behind, and it
  runs before the push that would repair it. Guard every `.module` access.
- **A recovery path must not depend on the thing it is recovering.** The
  Restart-TouchDesigner button first asked `osascript ... to quit` with a 30s
  timeout -- which is exactly what a wedged TouchDesigner cannot answer. It
  raised, abandoned the restart before relaunching, and left no TouchDesigner at
  all. Ask briefly, then `pkill`, then poll for the process to actually be gone.
- **A stopped run strands the recorder.** Halting playback leaves
  `_mcp_movieout` in the network and every later render refuses to start, so the
  stop path tears it down (`render.stop_recording`).
- **A paused timeline strands a render.** `render` schedules its finalize with
  `delayFrames`, which only advances while playing, so pausing mid-record leaves
  `_mcp_movieout` in the network and the PNGs on disk. Recover with
  `run("_render_realtime_stop({})")`.

### Lyrics

Always user-supplied — typed, imported, or transcribed from a vocal stem. None is
bundled with the source; `data/cues.tsv` and per-song `cues.tsv` are gitignored.

- **Trim the silent lead-in before uploading to Whisper; never pad it.** A long
  quiet intro makes it drop the opening line outright — on one song it lost the
  whole first couplet and hung the *second* line's words on the first line's
  timestamps, so the cue count, the coverage and the end time all looked healthy
  and nothing reported a problem. Measured on that song: whole file at 64k and
  at 128k both lost it, a second of prepended silence also lost it, and trimming
  to the first sung note recovered it. Keep the lead-in small — half a second of
  silence was enough to send the model off into hallucinated captions.
- **`adelay` with one value delays only the first channel.** Downmixing to mono
  afterwards restores the original timing from the untouched second channel, so
  the shift vanishes while the caller still corrects for it — every word a
  second out, silently. Use `adelay=delays=N:all=1`, or seek instead.
- **Language is worth more than any audio setting.** Auto-detection gave 43
  words on a Hindi track where `language="hi"` gave 121, from identical audio.
