# Contributing

Thanks for your interest in contributing to the TouchDesigner MCP Server! We welcome contributions of all kinds — bug fixes, new tools, examples, docs, and ideas.

## Getting Started

1. Fork the repo and clone it locally
2. Drag `td_mcp_server.tox` into any TouchDesigner project — the `.tox` is fully self-contained (server code is embedded, no file paths to configure)
3. The MCP server starts automatically on port `9988`
4. Connect your MCP client to `http://localhost:9988/mcp`
5. To run examples, set your TD project's folder to the repo root so `project.folder` resolves the scripts

## Project Structure

- `scripts/td_mcp_server.py` — the MCP server (single file, runs inside TD)
- `examples/` — example scripts that build TD networks programmatically
- `td_mcp_server.tox` — pre-wired component for drag-and-drop install
- `.mcp.json` — MCP client config

## Making Changes

### Server (`scripts/td_mcp_server.py`)

The server is a single Python file with no external dependencies beyond TD's stdlib + numpy. To add a new tool:

1. Add its JSON Schema to the `TOOLS` list
2. Write a `handle_<tool_name>(args)` function
3. Add it to the `TOOL_HANDLERS` dict

After modifying the server script, reload it in TD by reading the file and writing to the handler DAT's `.text`.

### Examples

Example scripts live in `examples/` and should be runnable via:
```
td_run: exec(open(project.folder + '/examples/<name>.py').read())
```

Each example should clean up after itself (destroy operators if re-running) and print a confirmation message on completion.

### Rebuilding the `.tox`

The `.tox` is a binary TouchDesigner component export. After changing `scripts/td_mcp_server.py`, rebuild it by running inside TD:

```
td_run: exec(open(project.folder + '/scripts/rebuild_tox.py').read())
```

This syncs the latest server script into the component and re-exports `td_mcp_server.tox`.

## Submitting a PR

1. Create a branch from `main`
2. Make your changes
3. Test in TouchDesigner — `.toe` files are binary and gitignored, so describe your testing setup in the PR
4. Open a pull request with a clear description of what changed and why

## Reporting Issues

Open an issue on GitHub. Include:
- TouchDesigner version and OS
- MCP client you're using
- Steps to reproduce
- Any error messages from TD's textport or your MCP client

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
