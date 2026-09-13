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
    lyric_grid/  the song's words, lit on cue     (family: lyric)
    pulse_grid/  the beat as light, no words      (family: beatsync)
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
   project; without one, provisioning falls back to forking the open project
4. `lyricfield/types/<slug>/__init__.py` — `TYPE = VideoType(...)`

**Every tunable a type declares must be consumed by its `field.py` or its
`build.py`.** Pushing a value TD ignores is worse than not having the knob: it
reports success and changes nothing. That was true of 45 of the 51 values pushed
before types existed. The split is: `field.py` reads what changes per frame;
`build.py` bakes what belongs to the network (font, resolution, the glow and
bloom expressions).

### Concepts

- **Workspace** — one folder per song under `~/lyricfield-projects/<slug>/`:
  `project.toe`, `config.toml`, `cues.tsv`, `source/`, `stems/`, `exports/`.
  A new song's `.toe` is forked from whatever TD currently has open; there is
  deliberately no checked-in template (binary, undiffable, stale within a day).
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
