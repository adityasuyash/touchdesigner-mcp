"""
Rebuild td_mcp_server.tox from the latest scripts/td_mcp_server.py.

Run inside TouchDesigner via:
    td_run: exec(open(project.folder + '/scripts/rebuild_tox.py').read())

This syncs the server script into the td_mcp_server component's handler DAT
and re-exports the .tox file.
"""

import os

root = op('/project1')
comp = root.op('td_mcp_server')
if not comp:
    raise RuntimeError("td_mcp_server component not found under /project1")

handler = comp.op('mcp_handler')
if not handler:
    raise RuntimeError("mcp_handler DAT not found inside td_mcp_server")

# Read the latest server script from disk
script_path = project.folder + '/scripts/td_mcp_server.py'
if not os.path.exists(script_path):
    raise RuntimeError(f"Server script not found: {script_path}")

with open(script_path, 'r') as f:
    handler.text = f.read()

# Export the .tox
tox_path = project.folder + '/td_mcp_server.tox'
comp.save(tox_path)

print(f"Synced {script_path} -> {handler.path}")
print(f"Exported {tox_path}")
