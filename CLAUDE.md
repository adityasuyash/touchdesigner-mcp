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
- `example.toe` — self-contained demo project (not tracked in git, binary)

## Working with TouchDesigner

- Operator paths are absolute (e.g. `/project1/out`). The root container is auto-discovered via `me.parent()`.
- `.toe` files are binary — can't be diffed or merged. All `.toe` files are gitignored.
- TD's Python environment is embedded (no pip). Only stdlib + numpy are available.
- To set expressions on parameters, use `par.name.expr = "..."` — assigning a string directly to a numeric par will error.
- After writing a GLSL shader, call `op.par.loaduniformnames.pulse()` to auto-detect uniforms.

## lyricfield — the lyric-video system

A second project lives in `lyricfield/`. It uses this MCP server as transport but
is otherwise independent: lyric videos as a dense character grid, rendered by
TouchDesigner and driven entirely from files.

**The repo is the source of truth.** TD holds a thin shell (a Script TOP, cue and
character DATs, the render chain); `lyricfield/sync.py` pushes behaviour in. Edit
`lyricfield/td/field_callbacks.py` here — never in the DAT, or the next push
overwrites it.

```
lyricfield/
  config.py      tunables + the constraints between them (validate() before render)
  cues.py        per-word cue table, TSV, hand-editable
  separate.py    Demucs stem separation (shells out to the CLI)
  transcribe.py  Groq Whisper -> word-level cues
  analysis.py    silences, kick entry, tempo, beat phase
  pipeline.py    prepare(): separate -> analyse -> transcribe, resumable
  styles.py      named reusable looks + video previews
  workspace.py   one folder per song
  td_client.py   JSON-RPC client for :9988
  sync.py        push repo -> TD, pull cue tables out
  render.py      capture, container validation, stem muxing, stills
  ui/            control UI (python -m lyricfield.ui.server -> :8765)
  td/            code that runs inside TouchDesigner
```

Run the UI and work from there; every stage also has a CLI entry point.

### Concepts

- **Workspace** — one folder per song under `~/lyricfield-projects/<slug>/`:
  `project.toe`, `config.toml`, `cues.tsv`, `source/`, `stems/`, `exports/`.
  A new song's `.toe` is forked from whatever TD currently has open; there is
  deliberately no checked-in template (binary, undiffable, stale within a day).
- **Style** — `Config` minus `track`, so grid/look/cueing/beat are reusable across
  songs and applying one provably cannot touch song data. Stored in `styles/`
  (tracked) with a short video preview, because motion is what distinguishes a
  style and a still cannot show it.

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

### Rendering and verification

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

### Lyrics

Always user-supplied — typed, imported, or transcribed from a vocal stem. None is
bundled with the source; `data/cues.tsv` and per-song `cues.tsv` are gitignored.
