"""
Rebuild td_mcp_server.tox from the latest scripts/td_mcp_server.py.

Run inside TouchDesigner via:
    td_run: REPO = '/path/to/touchdesigner-mcp'; exec(open(REPO + '/scripts/rebuild_tox.py').read())

This syncs the server script into the td_mcp_server component's handler DAT
and re-exports the .tox file.

`REPO` is read from the exec scope if set, and falls back to `project.folder`.
That fallback used to be the only option, and it broke as soon as the open
project stopped being the repo: lyricfield keeps one project per song under
~/lyricfield-projects, so `project.folder` is a song's directory and the script
failed with a FileNotFoundError naming a path nobody had asked for.
"""

import os

repo = globals().get('REPO') or project.folder
root = op('/project1')
comp = root.op('td_mcp_server')
if not comp:
    raise RuntimeError("td_mcp_server component not found under /project1")

handler = comp.op('mcp_handler')
if not handler:
    raise RuntimeError("mcp_handler DAT not found inside td_mcp_server")

# Read the latest server script from disk
script_path = os.path.join(repo, 'scripts', 'td_mcp_server.py')
if not os.path.exists(script_path):
    raise RuntimeError(f"Server script not found: {script_path}")

with open(script_path, 'r') as f:
    handler.text = f.read()

# Export the .tox
tox_path = os.path.join(repo, 'td_mcp_server.tox')
comp.save(tox_path)

print(f"Synced {script_path} -> {handler.path}")
print(f"Exported {tox_path}")
