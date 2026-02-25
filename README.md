# TouchDesigner MCP Server

An [MCP](https://modelcontextprotocol.io/) server that runs inside TouchDesigner, giving AI agents full control over your project — execute Python, inspect operators, read/write DATs, and capture visual output.

![Raymarched monolith with feedback loop post-processing](examples/hero_monolith.gif)

![Black hole with gravitational lensing and accretion disk](examples/event_horizon.gif)

![Audio-reactive infinite machine with feedback processing](examples/infinite_machine.gif)

*Built by Claude Code with Opus 4.6 using this MCP server*

## Quick Start

1. Drag `td_mcp_server.tox` into your project — server starts on port `9988`
2. Point your MCP client at `http://localhost:9988/mcp`
3. Start building

The `.tox` is self-contained — no file paths to configure.

MCP client setup: [Claude Code](https://docs.anthropic.com/en/docs/claude-code/tutorials/set-up-mcp) · [Cursor](https://docs.cursor.com/context/model-context-protocol) · [Windsurf](https://docs.windsurf.com/windsurf/mcp)

### Manual Setup

If you prefer not to use the `.tox`:

1. Create a Web Server DAT, set port to `9988`, enable Active
2. Create a TextDAT with the contents of [`scripts/td_mcp_server.py`](scripts/td_mcp_server.py)
3. Set the Web Server DAT's callbacks to point at your TextDAT

## Tools

| Tool | Description |
|------|-------------|
| `run` | Execute Python code — expressions return values directly, multi-line code captures stdout |
| `inspect` | Detailed operator info — channels, params, errors, connections |
| `set` | Set operator parameters with validation — constant values and/or expressions |
| `create` | Create an operator with position, params, expressions, and wiring in one call (requires `nodeX`/`nodeY`) |
| `wire` | Batch-wire operator connections and parameter expressions with auto-incrementing input indices |
| `read` | Read a TextDAT (with optional offset/limit) |
| `write` | Overwrite a TextDAT (creates if missing) |
| `edit` | Find/replace within a TextDAT |
| `list` | List operators under a container, filterable by family/pattern |
| `docs` | Look up params, menus, defaults, and connectors for any op type |
| `observe` | Capture a snapshot (PNG) or animated GIF of the current visual output |
| `render` | Render MP4 video using TD-native recording — supports audio capture, auto or manual start/stop |
| `map` | Render the operator network as a text map with connections, positions, and non-default params |

### `network_map` example

Output from the three example projects ([full source](examples/network_map.dot)):

```dot
digraph network {
    rankdir=LR;
    ...
    glsl_main -> out;
    fb_seed -> fb_comp -> fb_hsv -> fb_level -> fb_out;
    fb_level -> fb_feedback [style=dashed label="feedback"];
    fb_feedback -> fb_transform -> fb_comp;
    pf_lfo1 -> pf_merge; pf_lfo2 -> pf_merge; pf_noise_chop -> pf_merge;
    pf_glsl -> pf_out;
}
```

## Claude Code Skill

This repo includes a [Claude Code skill](https://docs.anthropic.com/en/docs/claude-code/skills) at `.claude/skills/touchdesigner-building/` that teaches the agent how to use the MCP tools effectively — correct parameter names, GLSL workflow, feedback loop wiring, the iterative observe loop, and common debugging steps.

Claude Code loads the skill automatically when it detects a relevant task (creating operators, writing shaders, setting parameters, etc.). No manual setup is needed if you're already using this repo.

**To use the skill in a different project**, copy the `.claude/skills/touchdesigner-building/` directory into your project's `.claude/skills/` folder and make sure your `.mcp.json` points at the running MCP server.

## How It Works

Implements [MCP Streamable HTTP](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http) (JSON-RPC over POST) on a Web Server DAT. No external dependencies. The root operator is auto-discovered via `me.parent()`.

## Requirements

- TouchDesigner 2024+
- Any MCP-compatible client

## License

MIT
