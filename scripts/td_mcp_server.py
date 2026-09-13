"""
MCP Server for TouchDesigner - Web Server DAT request handler.
Implements MCP Streamable HTTP protocol (JSON-RPC over POST to /mcp).

13 tools: run, inspect, set, create, wire, observe, render, read, write, edit, list, docs, map

Attach to a Web Server DAT (webserver1) on port 9988.
"""

import json
import base64
import collections as _collections
import uuid as _uuid


# ---------------------------------------------------------------------------
# MCP Protocol Constants
# ---------------------------------------------------------------------------
MCP_VERSION = "2025-03-26"
SERVER_INFO = {
    "name": "touchdesigner",
    "version": "1.0.0",
}
CAPABILITIES = {
    "tools": {},
}

# ---------------------------------------------------------------------------
# Tool Definitions
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "run",
        "description": "Execute Python code inside TouchDesigner and return the result. For expressions (e.g. \"op('/project1/out').width\"), returns the value directly. For multi-line code, captures print output. Returns errors with full tracebacks, and any operator-level errors (shader compile failures, missing inputs) detected after execution. IMPORTANT: Use the docs tool to look up correct parameter names before setting them — TD names are often abbreviated (e.g. 'rough' not 'roughness'). To set expressions on parameters, use par.expr = '...' — assigning a string to a numeric par will error.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute in TD context",
                },
            },
            "required": ["code"],
        },
    },
    {
        "name": "inspect",
        "description": "Get detailed info about any TouchDesigner operator: type, channels (with values), parameters, errors, connections, extensions. Path should be absolute like '/project1/uniforms'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute operator path (e.g. '/project1/uniforms')",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "set",
        "description": (
            "Set parameters on a TouchDesigner operator. "
            "Validates parameter names and reports unknown ones as errors. "
            "Use 'params' for constant values and 'exprs' for expression strings. "
            "Returns the evaluated value of each successfully set parameter."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute operator path (e.g. '/project1/my_glsl')",
                },
                "params": {
                    "type": "object",
                    "description": "Dict of param name → constant value to set",
                    "additionalProperties": True,
                },
                "exprs": {
                    "type": "object",
                    "description": "Dict of param name → expression string (sets expression mode)",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "create",
        "description": (
            "Create a new operator with optional parameter setting and wiring. "
            "Handles type resolution, destroy-before-create (prevents duplicates), "
            "param/expression setting, and input/output connections in one call. "
            "Use docs tool first to look up correct type constants and parameter names."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": "Operator type constant (e.g. 'glslTOP', 'lfoCHOP', 'noiseTOP'). Use docs(type='list_types') to find valid constants.",
                },
                "name": {
                    "type": "string",
                    "description": "Name for the new operator",
                },
                "parent": {
                    "type": "string",
                    "description": "Container to create in (default '/project1')",
                },
                "params": {
                    "type": "object",
                    "description": "Dict of param name → constant value to set",
                    "additionalProperties": True,
                },
                "exprs": {
                    "type": "object",
                    "description": "Dict of param name → expression string",
                    "additionalProperties": {"type": "string"},
                },
                "inputs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Operator paths to connect as inputs (order = input index)",
                },
                "output": {
                    "type": "string",
                    "description": "Operator path to connect this op's output to (first available input)",
                },
                "nodeX": {
                    "type": "integer",
                    "description": "Network position X. Use map tool to see existing layout and place nearby.",
                },
                "nodeY": {
                    "type": "integer",
                    "description": "Network position Y. Use map tool to see existing layout and place nearby.",
                },
            },
            "required": ["type", "name", "nodeX", "nodeY"],
        },
    },
    {
        "name": "observe",
        "description": "Observe the current visual output. Two modes: 'snapshot' (default) returns a single PNG frame — fast and small. 'animated' returns an animated GIF — shows motion but larger response. Use snapshot for quick checks, animated when you need to see movement.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["snapshot", "animated"],
                    "description": "Capture mode. 'snapshot' (default): single PNG frame, small response. 'animated': multi-frame GIF, shows motion.",
                },
                "duration": {
                    "type": "number",
                    "description": "Duration in seconds (default 2.0, max 4.0). For snapshot mode, advances the timeline this many seconds and captures the last frame.",
                },
                "fps": {
                    "type": "integer",
                    "description": "Frames per second for animated mode (default 15, max 30). Ignored for snapshot.",
                },
                "top": {
                    "type": "string",
                    "description": "Absolute path to the TOP to capture (e.g. '/project1/out'). Auto-detected if omitted.",
                },
                "filename": {
                    "type": "string",
                    "description": "Save the capture to this path instead of a temp file. Relative paths resolve from the project folder.",
                },
            },
        },
    },
    {
        "name": "read",
        "description": "Read the text content of a DAT operator. Returns the full text and line count. Path should be absolute like '/project1/shader_code'.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute operator path to a DAT (e.g. '/project1/shader_code')",
                },
                "offset": {
                    "type": "integer",
                    "description": "Start line (1-indexed). Omit to read from the beginning.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max lines to return. Omit to read all.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write",
        "description": "Overwrite the full text content of a DAT operator. Creates a new TextDAT if the operator doesn't exist (under the parent path).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute operator path to a DAT (e.g. '/project1/shader_code')",
                },
                "content": {
                    "type": "string",
                    "description": "The full text content to write",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit",
        "description": "Find and replace text within a DAT operator. The old_string must match exactly once in the DAT's text (unless replace_all is true). Mirrors the Edit tool semantics.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute operator path to a DAT",
                },
                "old_string": {
                    "type": "string",
                    "description": "The exact text to find",
                },
                "new_string": {
                    "type": "string",
                    "description": "The replacement text",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": "Replace all occurrences (default false)",
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "list",
        "description": "List all operators under a given parent path. Returns name, type, family, and basic info for each operator. Optionally filter by family (TOP, CHOP, SOP, DAT, COMP, MAT) and/or name pattern.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to a container operator (e.g. '/project1')",
                },
                "family": {
                    "type": "string",
                    "description": "Filter by operator family: TOP, CHOP, SOP, DAT, COMP, MAT. Omit to list all.",
                },
                "pattern": {
                    "type": "string",
                    "description": "Optional glob pattern to filter operator names (e.g. 'fb_*'). Uses Python fnmatch.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "docs",
        "description": (
            "Look up documentation for a TouchDesigner operator type. "
            "Returns available parameters (grouped by page, with defaults and menu options), "
            "input/output connector info, and the Python type constant name for use with create(). "
            "Accepts either a type constant like 'glslTOP' or 'lfoCHOP', or an existing operator path like '/project1/out'. "
            "Use 'list_types' as the type to get all available operator type constants for a family."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "description": (
                        "Operator type constant (e.g. 'glslTOP', 'lfoCHOP', 'compositeTOP') "
                        "OR an absolute operator path to inspect its type. "
                        "Use 'list_types' to list all available type constants."
                    ),
                },
                "family": {
                    "type": "string",
                    "description": "When type='list_types', filter by family: TOP, CHOP, SOP, DAT, COMP, MAT.",
                },
                "filter": {
                    "type": "string",
                    "description": "Optional substring filter for parameter names (e.g. 'freq' to find frequency-related params).",
                },
            },
            "required": ["type"],
        },
    },
    {
        "name": "map",
        "description": (
            "Render a text map of the operator network under a container. "
            "Shows all operators, their connections (signal flow), and non-default parameters. "
            "Use this to understand the full topology of a TD project at a glance. "
            "Optionally filter by operator family."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to a container operator (e.g. '/project1')",
                },
                "family": {
                    "type": "string",
                    "description": "Filter by operator family: TOP, CHOP, SOP, DAT, COMP, MAT. Omit to show all.",
                },
                "include_defaults": {
                    "type": "boolean",
                    "description": "Include parameters at default values (default: false, only shows non-default params).",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "wire",
        "description": (
            "Batch-wire operator connections and/or parameter expressions. "
            "For operator connections, auto-increments input indices when multiple sources target the same operator. "
            "For parameter expressions, sets the expression referencing a source op/channel."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "connections": {
                    "type": "array",
                    "description": "Operator output→input wires. Input index auto-increments per target.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from": {"type": "string", "description": "Source op path"},
                            "from_output": {"type": "integer", "description": "Output connector index (default 0)"},
                            "to": {"type": "string", "description": "Target op path"},
                            "to_input": {"type": "integer", "description": "Input connector index. Auto-assigned if omitted."},
                        },
                        "required": ["from", "to"],
                    },
                },
                "expressions": {
                    "type": "array",
                    "description": "Parameter expression wires. Sets target param's expression to reference source op/channel.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "from": {"type": "string", "description": "Source op path (e.g. CHOP)"},
                            "channel": {"type": "string", "description": "Channel name on source op"},
                            "to": {"type": "string", "description": "Target op path"},
                            "param": {"type": "string", "description": "Parameter name on target to set expression on"},
                        },
                        "required": ["from", "to", "param"],
                    },
                },
            },
        },
    },
    {
        "name": "render",
        "description": (
            "Render high-quality MP4 video from a TOP using TD-native recording. "
            "Uses MovieFileOut TOP (PNG image sequence) + optional AudioFileOut CHOP (WAV) "
            "for synchronized audio capture. Works on all TD license tiers.\n\n"
            "Starts recording and auto-finalizes into MP4 when duration elapses. "
            "TD must be playing (timeline running) for frames to record.\n\n"
            "Requires ffmpeg on the system for the final MP4 encode."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "top": {
                    "type": "string",
                    "description": "Absolute path to the TOP to render (e.g. '/project1/out'). Auto-detected if omitted.",
                },
                "output": {
                    "type": "string",
                    "description": "Output file path for the MP4. Relative paths resolve from the project folder.",
                },
                "duration": {
                    "type": "number",
                    "description": "Duration in seconds.",
                },
                "fps": {
                    "type": "integer",
                    "description": "Frames per second (default 30)",
                },
                "audio_chop": {
                    "type": "string",
                    "description": "Absolute path to a CHOP for audio capture (e.g. '/project1/ex3_audio').",
                },
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "status"],
                    "description": (
                        "'start' (default) begins recording. 'stop' finalizes a recording "
                        "immediately — needed because the automatic finalize is scheduled in "
                        "timeline frames and never fires if playback is paused, which strands "
                        "the recording operators and frames. 'status' reports what is active."
                    ),
                },
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_root():
    """Discover the project root: parent of the Web Server DAT running this script."""
    try:
        return me.parent()
    except Exception:
        return None


def _find_output_top():
    """Find the best TOP to capture. Tries common names, then falls back to any TOP."""
    root = _get_root()
    if root is None:
        return None
    # Try common output names
    for name in ('out', 'out1', 'render', 'comp', 'null1'):
        t = root.op(name)
        if t is not None and t.family == 'TOP':
            return t
    # Fallback: find any TOP in the root
    for child in root.children:
        if child.family == 'TOP':
            return child
    return None


_OBSERVE_WIDTH = 480
_OBSERVE_GIF_WIDTH = 320
_OBSERVE_FPS = 15
_OBSERVE_GIF_FPS = 10
_OBSERVE_DURATION = 2.0
_OBSERVE_MAX_FRAMES = 60


def _encode_single_png(frame):
    """Encode a single RGB uint8 numpy array as a PNG. Pure Python."""
    import struct
    import zlib

    h, w, _ = frame.shape

    def _chunk(chunk_type, data):
        raw = chunk_type + data
        return struct.pack('>I', len(data)) + raw + struct.pack('>I', zlib.crc32(raw) & 0xFFFFFFFF)

    rows = bytearray()
    for y in range(h):
        rows.append(0)  # filter byte: None
        rows.extend(frame[y].tobytes())
    compressed = zlib.compress(bytes(rows), 6)

    buf = bytearray()
    buf += b'\x89PNG\r\n\x1a\n'
    buf += _chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
    buf += _chunk(b'IDAT', compressed)
    buf += _chunk(b'IEND', b'')
    return bytes(buf)


def _encode_gif_ffmpeg(frames, fps, out_path):
    """Encode frames as an animated GIF using ffmpeg (two-pass for optimal palette)."""
    import subprocess
    import tempfile as _tempfile
    import os as _os

    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found — needed for animated GIF encoding")

    h, w, _ = frames[0].shape

    # Write raw RGB frames to a temp file
    raw_path = _tempfile.mktemp(suffix='.rgb')
    try:
        with open(raw_path, 'wb') as f:
            for frame in frames:
                f.write(frame.tobytes())

        # Two-pass GIF: first generate optimal palette, then encode with it
        palette_path = _tempfile.mktemp(suffix='.png')
        try:
            # Pass 1: generate palette from all frames
            subprocess.run([
                ffmpeg, '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                '-s', f'{w}x{h}', '-r', str(fps), '-i', raw_path,
                '-vf', 'palettegen=max_colors=256:stats_mode=full',
                palette_path,
            ], capture_output=True, timeout=30)

            # Pass 2: encode GIF using the palette
            subprocess.run([
                ffmpeg, '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
                '-s', f'{w}x{h}', '-r', str(fps), '-i', raw_path,
                '-i', palette_path,
                '-lavfi', 'paletteuse=dither=sierra2_4a',
                '-loop', '0', out_path,
            ], capture_output=True, timeout=30)
        finally:
            if _os.path.exists(palette_path):
                _os.unlink(palette_path)
    finally:
        if _os.path.exists(raw_path):
            _os.unlink(raw_path)


# ---------------------------------------------------------------------------
# Frame Capture
#
# Captures frames synchronously by advancing the timeline and force-cooking
# the operator chain. No background buffer needed.
# ---------------------------------------------------------------------------

import numpy as _np


def _force_cook_chain(o, visited=None):
    """Recursively force-cook an operator and all its inputs."""
    if visited is None:
        visited = set()
    if o.path in visited:
        return
    visited.add(o.path)
    for inp in o.inputs:
        _force_cook_chain(inp, visited)
    o.cook(force=True)


def _capture_frame(top, width=_OBSERVE_WIDTH):
    """Capture a single downsampled RGB frame from a TOP."""
    _force_cook_chain(top)
    arr = top.numpyArray()  # (h, w, 4) float32 RGBA
    rgb = (arr[::-1, :, :3] * 255).clip(0, 255).astype(_np.uint8)
    src_h, src_w = rgb.shape[:2]
    new_w = width
    new_h = int(src_h * (new_w / src_w))
    ys = _np.linspace(0, src_h - 1, new_h).astype(int)
    xs = _np.linspace(0, src_w - 1, new_w).astype(int)
    return rgb[ys][:, xs]


# ---------------------------------------------------------------------------
# Tool Handlers
# ---------------------------------------------------------------------------

def handle_observe(args):
    """Observe the current output. Supports snapshot (single PNG) and animated (GIF) modes.

    Both modes advance the timeline and force-cook the operator chain.
    Snapshot returns a single frame; animated returns a multi-frame GIF.
    """
    top_path = args.get('top')
    mode = args.get('mode', 'snapshot')

    # Find or validate the TOP
    if top_path:
        out_top = op(top_path)
        if out_top is None:
            return {"error": f"Operator not found: {top_path}"}
        if out_top.family != 'TOP':
            return {"error": f"Not a TOP: {top_path} (family={out_top.family})"}
    else:
        out_top = _find_output_top()
        if out_top is None:
            return {"error": "No output TOP found"}

    duration = min(args.get('duration', _OBSERVE_DURATION), 4.0)
    is_animated = mode == 'animated'
    default_fps = _OBSERVE_GIF_FPS if is_animated else _OBSERVE_FPS
    fps = min(args.get('fps', default_fps), 30)
    capture_width = _OBSERVE_GIF_WIDTH if is_animated else _OBSERVE_WIDTH
    num_frames = max(1, min(int(duration * fps), _OBSERVE_MAX_FRAMES))

    # Capture frames by advancing the timeline
    frame_step = max(1, int(round(me.time.rate / fps)))
    frames = []
    for i in range(num_frames):
        me.time.frame += frame_step
        frames.append(_capture_frame(out_top, width=capture_width))

    try:
        filename = args.get('filename')

        if mode == 'animated':
            # Animated GIF via ffmpeg (two-pass palette for best quality)
            import os as _os
            if filename:
                if not _os.path.isabs(filename):
                    filename = _os.path.join(project.folder, filename)
            else:
                import tempfile as _tempfile
                tmp = _tempfile.NamedTemporaryFile(
                    prefix='td_observe_', suffix='.gif', delete=False
                )
                tmp.close()
                filename = tmp.name

            _encode_gif_ffmpeg(frames, fps, filename)

            with open(filename, 'rb') as f:
                gif_data = f.read()

            b64 = base64.b64encode(gif_data).decode('ascii')
            return {"_observe_b64": b64, "_observe_mime": "image/gif",
                    "_observe_top": out_top.path, "file": filename}
        else:
            # Snapshot — single PNG frame (last captured), very small
            snapshot = _encode_single_png(frames[-1])

            if filename:
                import os as _os
                if not _os.path.isabs(filename):
                    filename = _os.path.join(project.folder, filename)
            else:
                import tempfile as _tempfile
                tmp = _tempfile.NamedTemporaryFile(
                    prefix='td_observe_', suffix='.png', delete=False
                )
                tmp.close()
                filename = tmp.name

            with open(filename, 'wb') as f:
                f.write(snapshot)

            b64 = base64.b64encode(snapshot).decode('ascii')
            return {"_observe_b64": b64, "_observe_mime": "image/png",
                    "_observe_top": out_top.path, "file": filename}
    except Exception as e:
        return {"error": str(e)}


def _find_ffmpeg():
    """Find ffmpeg binary across platforms."""
    import os as _os
    import shutil as _shutil

    # shutil.which checks PATH
    found = _shutil.which('ffmpeg')
    if found:
        return found

    # Common install locations by platform
    candidates = [
        # macOS Homebrew
        '/opt/homebrew/bin/ffmpeg',
        '/usr/local/bin/ffmpeg',
        # Linux
        '/usr/bin/ffmpeg',
        '/snap/bin/ffmpeg',
        # Windows
        'C:/ffmpeg/bin/ffmpeg.exe',
        'C:/Program Files/ffmpeg/bin/ffmpeg.exe',
    ]
    for path in candidates:
        if _os.path.isfile(path):
            return path

    return None


def handle_render(args):
    """Render MP4 from a TOP using TD-native MovieFileOut + optional AudioFileOut.

      action='start' (default) → creates operators, begins recording, returns
      action='stop'            → finalizes now; ffmpeg combines frames + audio
      action='status'          → what is recording, if anything

    'stop' exists because the automatic finalize is scheduled with delayFrames,
    which only advances while the timeline plays. Pause mid-record and the
    recording is stranded: operators left in the network, frames left on disk.
    """
    action = args.get('action', 'start')
    if action == 'stop':
        return _render_realtime_stop(args)
    if action == 'status':
        if not _active_recording:
            return {"recording": False}
        # How far along, in frames actually written rather than in wall clock.
        # The recording writes one PNG per captured frame into tmp_dir, so
        # counting them is the only honest measure of progress: TouchDesigner
        # cooks slower than real time and by a factor that varies with the
        # network, so elapsed seconds say nothing about how much is done.
        import os as _os
        tmp_dir = _active_recording.get('tmp_dir')
        fps = float(_active_recording.get('fps') or 0)
        duration = float(_active_recording.get('duration') or 0)
        written = 0
        try:
            written = sum(1 for n in _os.listdir(tmp_dir) if n.endswith('.png'))
        except Exception:
            pass
        expected = int(fps * duration) if fps and duration else 0
        return {"recording": True,
                "output": _active_recording.get('output'),
                "top": _active_recording.get('top_path'),
                "tmp_dir": tmp_dir,
                "frames": written,
                "expected": expected,
                "fraction": round(min(1.0, written / expected), 4) if expected else None}
    return _handle_render_realtime(args)


# State for active realtime recordings
_active_recording = {}


def _handle_render_realtime(args):
    """Real-time render using TD-native MovieFileOut TOP + AudioFileOut CHOP.

    Records for the specified duration then auto-finalizes into MP4 via ffmpeg.
    Uses PNG image sequence (works on all TD license tiers) instead of H.264 direct encoding.
    """
    import os as _os
    import tempfile as _tempfile

    # Resolve source TOP
    top_path = args.get('top')
    if top_path:
        out_top = op(top_path)
        if out_top is None:
            return {"error": f"Operator not found: {top_path}"}
        if out_top.family != 'TOP':
            return {"error": f"Not a TOP: {top_path} (family={out_top.family})"}
    else:
        out_top = _find_output_top()
        if out_top is None:
            return {"error": "No output TOP found"}

    # Create recording ops in the same container as the source TOP
    # (TD connections can't cross container boundaries)
    container = out_top.parent()

    output = args.get('output', '')
    if not output:
        return {"error": "output path is required"}
    if not _os.path.isabs(output):
        output = _os.path.join(project.folder, output)

    out_dir = _os.path.dirname(output)
    if out_dir:
        _os.makedirs(out_dir, exist_ok=True)

    fps = args.get('fps', 30)
    duration = args.get('duration')
    audio_chop_path = args.get('audio_chop')

    if not duration:
        return {"error": "duration is required"}

    # Starting over a live recording used to destroy its operators and finalize
    # it against the new paths, losing both takes. Refuse instead.
    if _active_recording:
        return {
            "error": "a recording is already active; finalize it with "
                     "action='stop' before starting another",
            "active": _active_recording.get('output'),
            "tmp_dir": _active_recording.get('tmp_dir'),
        }

    # Extend the timeline if needed so the recording doesn't loop with hard cuts.
    #
    # The play range matters as much as the length. `rangestart`..`rangeend`
    # confines the playhead, and with `rangelimit` at "loop" it physically
    # cannot leave -- a frame set past `rangeend` is discarded with no error,
    # and playback wraps. Growing `end` alone therefore fixed nothing: a project
    # whose range was inherited from a 90-second song recorded the wrong part of
    # a 264-second one, under correct audio, and reported success.
    #
    # Measured against the timeline the recording actually plays, not `me.time`,
    # which can be a different component.
    tl = op('/local/time') or me.time
    needed_frames = int(float(duration) * tl.rate) + int(tl.rate)  # +1s buffer
    if tl.end < needed_frames:
        tl.end = needed_frames
    try:
        if tl.par.rangestart.eval() > 1:
            tl.par.rangestart = 1
        if tl.par.rangeend.eval() < tl.end:
            tl.par.rangeend = tl.end
    except AttributeError:
        pass            # a time component without a play range; nothing to widen

    # Create temp directory for image sequence
    tmp_dir = _tempfile.mkdtemp(prefix='td_render_')
    frame_base = _os.path.join(tmp_dir, 'frame')

    # Clean up any previous recording ops
    for name in ['_mcp_movieout', '_mcp_audioout']:
        old = container.op(name)
        if old:
            old.destroy()

    # Create MovieFileOut TOP (image sequence mode)
    movie_out = container.create(moviefileoutTOP, '_mcp_movieout')
    movie_out.par.type = 'imagesequence'
    movie_out.par.imagefiletype = 'png'
    movie_out.par.outputresolution = 'useinput'
    movie_out.par.file.expr = "'" + frame_base.replace('\\', '\\\\') + "' + me.fileSuffix"
    movie_out.par.fps = fps
    movie_out.par.leadingzerosdigits = 6
    movie_out.inputConnectors[0].connect(out_top)

    movie_out.par.limitlength = True
    movie_out.par.length = float(duration)
    movie_out.par.lengthunit = 'seconds'

    # Create AudioFileOut CHOP if audio source specified
    audio_file = None
    if audio_chop_path:
        audio_src = op(audio_chop_path)
        if audio_src is None:
            movie_out.destroy()
            return {"error": f"Audio CHOP not found: {audio_chop_path}"}

        audio_file = _os.path.join(tmp_dir, 'audio.wav')
        audio_out = container.create(audiofileoutCHOP, '_mcp_audioout')
        audio_out.par.filetype = 'wav'
        audio_out.par.codec = 'pcm16'
        audio_out.par.file = audio_file
        audio_out.inputConnectors[0].connect(audio_src)
        audio_out.par.record = True

    # Start video recording
    movie_out.par.record = True

    # Store state for the stop phase
    _active_recording.clear()
    _active_recording.update({
        'output': output,
        'tmp_dir': tmp_dir,
        'frame_base': frame_base,
        'audio_file': audio_file,
        'fps': fps,
        'duration': duration,
        'top_path': out_top.path,
        'container_path': container.path,
        'resolution': f"{out_top.width}x{out_top.height}",
    })

    # Schedule ffmpeg mux after recording completes
    delay_frames = int(float(duration) * me.time.rate) + int(me.time.rate * 2)  # +2s buffer
    run("_auto_finalize_render()", delayFrames=delay_frames)

    msg = f"Recording started → {out_top.path} at {fps}fps for {duration}s"
    if audio_chop_path:
        msg += f" with audio from {audio_chop_path}"
    msg += f"\nFrames saving to: {tmp_dir}"
    msg += f"\nWill auto-finalize into MP4 after {duration}s."

    return {
        "ok": True,
        "recording": True,
        "message": msg,
        "top": out_top.path,
        "fps": fps,
        "duration": duration,
        "audio": audio_chop_path or False,
    }


def _auto_finalize_render():
    """Called by TD's delayed run() after recording duration elapses. Runs ffmpeg to combine."""
    if not _active_recording:
        return  # already stopped manually

    result = _render_realtime_stop({})
    # Log result to textport
    if result.get('ok'):
        print(f"[MCP render] Auto-finalized: {result.get('file')} ({result.get('frames')} frames, {result.get('size_mb')}MB)")
    else:
        print(f"[MCP render] Auto-finalize error: {result.get('error', 'unknown')}")


def _render_realtime_stop(args):
    """Stop recording and combine frames + audio into MP4 via ffmpeg."""
    import os as _os
    import subprocess as _sp
    import glob as _glob

    if not _active_recording:
        return {"error": "No active recording."}

    rec = dict(_active_recording)
    _active_recording.clear()

    container = op(rec.get('container_path', ''))

    # Stop recording on both operators
    movie_out = container.op('_mcp_movieout') if container else None
    audio_out = container.op('_mcp_audioout') if container else None

    if movie_out:
        movie_out.par.record = False
    if audio_out:
        audio_out.par.record = False

    output = rec['output']
    tmp_dir = rec['tmp_dir']
    frame_base = rec['frame_base']
    audio_file = rec['audio_file']
    fps = rec['fps']

    # Find the rendered frames
    frame_pattern = frame_base + '*.png'
    frames = sorted(_glob.glob(frame_pattern))
    if not frames:
        # Clean up operators
        if movie_out:
            movie_out.destroy()
        if audio_out:
            audio_out.destroy()
        return {"error": f"No frames found at {frame_pattern}. Was the timeline playing?"}

    num_frames = len(frames)
    actual_duration = num_frames / fps

    # Combine with ffmpeg
    ffmpeg = _find_ffmpeg()
    if ffmpeg is None:
        return {
            "error": "ffmpeg not found — frames saved at " + tmp_dir,
            "frames": num_frames,
            "tmp_dir": tmp_dir,
        }

    # Build ffmpeg command: PNG sequence → H.264 MP4
    # TD names files like: frame.0.000000.png, frame.0.000001.png, ...
    # Detect the pattern from the first file to build the correct ffmpeg input
    first = _os.path.basename(frames[0])

    import re as _re
    # Match TD's naming: base.N.NNNNNN.ext (e.g. frame.0.000000.png)
    match = _re.search(r'^(.+)\.(\d+)\.(\d+)\.png$', first)
    if match:
        prefix = match.group(1)
        n_part = match.group(2)
        digits = len(match.group(3))
        start_number = int(match.group(3))
        seq_pattern = _os.path.join(tmp_dir, f'{prefix}.{n_part}.%0{digits}d.png')
    else:
        # Fallback: try simple numbered pattern
        match2 = _re.search(r'(\d+)\.png$', first)
        start_number = int(match2.group(1)) if match2 else 0
        digits = len(match2.group(1)) if match2 else 6
        seq_pattern = frame_base + f'%0{digits}d.png'

    cmd = [
        ffmpeg, '-y',
        '-framerate', str(fps),
        '-start_number', str(start_number),
        '-i', seq_pattern,
    ]

    # Add audio input if we have it
    if audio_file and _os.path.isfile(audio_file):
        cmd.extend(['-i', audio_file])

    cmd.extend([
        '-c:v', 'libx264',
        '-preset', 'slow',
        '-crf', '18',
        '-pix_fmt', 'yuv420p',
    ])

    if audio_file and _os.path.isfile(audio_file):
        cmd.extend(['-c:a', 'aac', '-b:a', '192k'])

    cmd.extend([
        '-movflags', '+faststart',
        '-shortest',
        output,
    ])

    try:
        result = _sp.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            stderr = result.stderr.decode('utf-8', errors='replace')
            return {
                "error": f"ffmpeg failed (code {result.returncode}): {stderr[-500:]}",
                "frames": num_frames,
                "tmp_dir": tmp_dir,
            }
    except Exception as e:
        return {"error": f"ffmpeg error: {e}", "frames": num_frames, "tmp_dir": tmp_dir}

    # Clean up temp files
    import shutil as _shutil
    try:
        _shutil.rmtree(tmp_dir, ignore_errors=True)
    except Exception:
        pass

    # Clean up TD operators
    if movie_out:
        movie_out.destroy()
    if audio_out:
        audio_out.destroy()

    size_mb = _os.path.getsize(output) / (1024 * 1024)
    return {
        "ok": True,
        "file": output,
        "resolution": rec.get('resolution', 'unknown'),
        "duration": round(actual_duration, 1),
        "fps": fps,
        "frames": num_frames,
        "size_mb": round(size_mb, 1),
        "realtime": True,
        "audio": bool(audio_file),
    }


# ---------------------------------------------------------------------------
# Dev / Introspection Tools
# ---------------------------------------------------------------------------

def handle_td_run(args):
    """Execute Python code in TD context. Tries eval first (for expressions), falls back to exec."""
    code = args.get('code', '')
    if not code:
        return {"error": "code is required"}

    import ast
    import io
    import sys
    import traceback

    # Determine if code is a single expression (use eval) or statements (use exec)
    is_expr = False
    try:
        ast.parse(code, mode='eval')
        is_expr = True
    except SyntaxError:
        pass

    # A single expression may still print — `print(x)` parses as an expression.
    # Capturing stdout on both paths stops that output being silently dropped,
    # which made the most natural probe anyone writes return nothing at all.
    scope = {}
    old_stdout = sys.stdout
    sys.stdout = captured = io.StringIO()
    error = None
    value = None
    try:
        if is_expr:
            value = eval(code, scope)
        else:
            # exec needs an explicit globals mapping, or names bound at the top
            # level of the submitted code are invisible inside any nested def.
            exec(code, scope)
    except Exception:
        error = traceback.format_exc()
    finally:
        sys.stdout = old_stdout

    if is_expr:
        output = captured.getvalue()
        if error:
            return {"ok": False, "error": error}
        result = {"ok": True, "result": _serialize(value)}
        if output:
            result["output"] = output
        op_errors = _scan_op_errors()
        if op_errors:
            result["warnings"] = op_errors
        return result

    output = captured.getvalue()
    result = {"ok": error is None}
    if output:
        result["output"] = output
    if error:
        result["error"] = error

    # Post-run: scan operators for TD-level errors (shader compile, missing inputs, etc.)
    if error is None:
        op_errors = _scan_op_errors()
        if op_errors:
            result["warnings"] = op_errors

    return result


def _scan_op_errors():
    """Scan all operators under root for TD-level errors (shader compile failures, etc.)."""
    root = _get_root()
    if root is None:
        return []
    errors = []
    try:
        for child in root.findChildren(depth=5):
            try:
                errs = child.errors()
                if errs:
                    # Filter out the MCP server's own container
                    if child == root or child.path == me.path:
                        continue
                    errors.append({
                        "op": child.path,
                        "type": child.type,
                        "errors": errs,
                    })
            except Exception:
                pass
    except Exception:
        pass
    return errors


def handle_inspect_op(args):
    """Get detailed info about a TD operator."""
    path = args.get('path', '')
    if not path:
        return {"error": "path is required"}

    target = op(path)
    if target is None:
        return {"error": f"Operator not found: {path}"}

    info = {
        "path": target.path,
        "type": target.type,
        "family": target.family,
    }

    # CHOP: list channels with current values
    if target.family == 'CHOP':
        channels = {}
        try:
            for i in range(target.numChans):
                ch = target[i]
                channels[ch.name] = round(float(ch[0]), 6) if target.numSamples > 0 else None
        except Exception as e:
            channels = {"error": str(e)}
        info["channels"] = channels
        info["numSamples"] = target.numSamples

    # TOP: resolution, pixel format
    elif target.family == 'TOP':
        try:
            info["resolution"] = [target.width, target.height]
            info["pixel_format"] = str(target.pixelFormat)
        except Exception:
            pass

    # DAT: row/col count, first few rows for text
    elif target.family == 'DAT':
        try:
            info["numRows"] = target.numRows
            info["numCols"] = target.numCols
            if target.numRows > 0 and target.numRows <= 5:
                info["text"] = target.text[:2000]
            elif target.numRows > 5:
                info["text_preview"] = target.text[:1000] + "..."
        except Exception:
            pass

    # Errors
    try:
        errs = target.errors()
        if errs:
            info["errors"] = errs
    except Exception:
        pass

    # Warnings
    try:
        warns = target.warnings()
        if warns:
            info["warnings"] = warns
    except Exception:
        pass

    # Extensions
    try:
        exts = [str(e) for e in target.extensions]
        if exts:
            info["extensions"] = exts
    except Exception:
        pass

    # Inputs/outputs
    try:
        info["inputs"] = [inp.path if inp else None for inp in target.inputs]
    except Exception:
        pass
    try:
        info["outputs"] = [out.path if out else None for out in target.outputs]
    except Exception:
        pass

    # Key custom parameters (if it's a Base COMP with a control panel)
    try:
        custom_pars = {}
        for p in target.customPars:
            try:
                custom_pars[p.name] = p.eval()
            except Exception:
                custom_pars[p.name] = str(p)
        if custom_pars:
            info["custom_pars"] = custom_pars
    except Exception:
        pass

    return info


# ---------------------------------------------------------------------------
# Parameter Set Tool
# ---------------------------------------------------------------------------

def _set_par(p, value):
    """Set a parameter value with menu validation. Returns (eval_value, error_or_None).

    Only a strict Menu constrains its value. A StrMenu (e.g. a Select CHOP's
    'channames', a Text TOP's 'font') takes any string and merely offers its menu
    as suggestions — validating those against menuNames rejects every legitimate
    value that is not already in the list.
    """
    if p.isMenu and str(p.style) == 'Menu' and isinstance(value, str):
        valid = p.menuNames
        if value not in valid:
            return None, f"invalid menu value '{value}' for '{p.name}' — valid: {list(valid)}"
    p.val = value
    return _serialize(p.eval()), None


def handle_set(args):
    """Set parameters on an operator with validation."""
    path = args.get('path', '')
    if not path:
        return {"error": "path is required"}

    params = args.get('params') or {}
    exprs = args.get('exprs') or {}
    if not params and not exprs:
        return {"error": "at least one of 'params' or 'exprs' must be provided"}

    target = op(path)
    if target is None:
        return {"error": f"Operator not found: {path}"}

    set_values = {}
    expr_values = {}
    errors = []

    # Set constant values
    for name, value in params.items():
        if not hasattr(target.par, name):
            errors.append(f"unknown parameter: '{name}'")
            continue
        try:
            p = getattr(target.par, name)
            val, err = _set_par(p, value)
            if err:
                errors.append(err)
            else:
                set_values[name] = val
        except Exception as e:
            errors.append(f"{name}: {e}")

    # Set expressions
    for name, expr in exprs.items():
        if not hasattr(target.par, name):
            errors.append(f"unknown parameter: '{name}'")
            continue
        try:
            p = getattr(target.par, name)
            p.expr = expr
            expr_values[name] = _serialize(p.eval())
        except Exception as e:
            errors.append(f"{name}: {e}")

    result = {"ok": len(errors) == 0, "path": target.path}
    if set_values:
        result["set"] = set_values
    if expr_values:
        result["expressions"] = expr_values
    if errors:
        result["errors"] = errors
    return result


def handle_create(args):
    """Create a new operator with optional params, expressions, and wiring."""
    type_name = args.get('type', '')
    op_name = args.get('name', '')
    if not type_name:
        return {"error": "type is required"}
    if not op_name:
        return {"error": "name is required"}

    parent_path = args.get('parent', '/project1')
    parent_op = op(parent_path)
    if parent_op is None:
        return {"error": f"Parent container not found: {parent_path}"}

    # Resolve type constant
    try:
        type_obj = eval(type_name)
    except Exception:
        return {"error": f"Unknown operator type: '{type_name}'. Use docs(type='list_types') to find valid constants."}

    # Destroy existing op with same name to prevent duplicates
    existing = parent_op.op(op_name)
    if existing is not None:
        existing.destroy()

    # Create the operator
    try:
        new_op = parent_op.create(type_obj, op_name)
    except Exception as e:
        return {"error": f"Failed to create {type_name} '{op_name}': {e}"}

    # Set network position
    if 'nodeX' in args:
        new_op.nodeX = int(args['nodeX'])
    if 'nodeY' in args:
        new_op.nodeY = int(args['nodeY'])

    errors = []

    # Apply params
    set_values = {}
    for name, value in (args.get('params') or {}).items():
        if not hasattr(new_op.par, name):
            errors.append(f"unknown parameter: '{name}'")
            continue
        try:
            p = getattr(new_op.par, name)
            val, err = _set_par(p, value)
            if err:
                errors.append(err)
            else:
                set_values[name] = val
        except Exception as e:
            errors.append(f"{name}: {e}")

    # Apply expressions
    expr_values = {}
    for name, expr in (args.get('exprs') or {}).items():
        if not hasattr(new_op.par, name):
            errors.append(f"unknown parameter: '{name}'")
            continue
        try:
            p = getattr(new_op.par, name)
            p.expr = expr
            expr_values[name] = _serialize(p.eval())
        except Exception as e:
            errors.append(f"{name}: {e}")

    # Wire inputs
    connected_inputs = []
    for i, input_path in enumerate(args.get('inputs') or []):
        src = op(input_path)
        if src is None:
            errors.append(f"input[{i}] not found: {input_path}")
            continue
        try:
            if i < len(new_op.inputConnectors):
                new_op.inputConnectors[i].connect(src)
            else:
                errors.append(f"input[{i}]: operator only has {len(new_op.inputConnectors)} input(s)")
                continue
            connected_inputs.append(input_path)
        except Exception as e:
            errors.append(f"input[{i}] ({input_path}): {e}")

    # Wire output
    output_path = args.get('output')
    connected_output = None
    if output_path:
        dst = op(output_path)
        if dst is None:
            errors.append(f"output not found: {output_path}")
        else:
            try:
                new_op.outputConnectors[0].connect(dst)
                connected_output = output_path
            except Exception as e:
                errors.append(f"output ({output_path}): {e}")

    result = {
        "ok": len(errors) == 0,
        "path": new_op.path,
        "type": type_name,
    }
    if set_values:
        result["set"] = set_values
    if expr_values:
        result["expressions"] = expr_values
    if connected_inputs:
        result["inputs"] = connected_inputs
    if connected_output:
        result["output"] = connected_output
    if errors:
        result["errors"] = errors
    return result


# ---------------------------------------------------------------------------
# Wire Tool
# ---------------------------------------------------------------------------

def handle_wire(args):
    """Batch-wire operator connections and parameter expressions."""
    connections = args.get('connections', [])
    expressions = args.get('expressions', [])

    if not connections and not expressions:
        return {"error": "At least one of 'connections' or 'expressions' is required"}

    results = []
    errors = []

    # --- Operator connections ---
    # Track next available input index per target op
    next_input = {}  # target_path -> next index

    for i, conn in enumerate(connections):
        src_path = conn.get('from', '')
        dst_path = conn.get('to', '')
        from_output = conn.get('from_output', 0)
        to_input = conn.get('to_input')  # None means auto-assign

        src = op(src_path)
        if src is None:
            errors.append(f"connection[{i}]: source not found: {src_path}")
            continue
        dst = op(dst_path)
        if dst is None:
            errors.append(f"connection[{i}]: target not found: {dst_path}")
            continue

        # Validate from_output
        if from_output < 0 or from_output >= len(src.outputConnectors):
            errors.append(f"connection[{i}]: output index {from_output} out of range for {src_path} (has {len(src.outputConnectors)})")
            continue

        # Auto-assign input index
        if to_input is None:
            if dst_path not in next_input:
                # Start after existing connections
                next_input[dst_path] = len(dst.inputConnectors[0].connections) if dst.inputConnectors else 0
            to_input = next_input[dst_path]
            next_input[dst_path] = to_input + 1
        else:
            # Explicit index — still update tracker so subsequent auto-assigns skip it
            if dst_path not in next_input or next_input[dst_path] <= to_input:
                next_input[dst_path] = to_input + 1

        try:
            dst.inputConnectors[to_input].connect(src.outputConnectors[from_output])
            results.append(f"{src_path} -> {dst_path}[{to_input}]")
        except Exception as e:
            errors.append(f"connection[{i}]: {e}")

    # --- Parameter expressions ---
    for i, expr in enumerate(expressions):
        src_path = expr.get('from', '')
        channel = expr.get('channel')
        dst_path = expr.get('to', '')
        param_name = expr.get('param', '')

        dst = op(dst_path)
        if dst is None:
            errors.append(f"expression[{i}]: target not found: {dst_path}")
            continue

        if not hasattr(dst.par, param_name):
            errors.append(f"expression[{i}]: param '{param_name}' not found on {dst_path}")
            continue

        src = op(src_path)
        if src is None:
            errors.append(f"expression[{i}]: source not found: {src_path}")
            continue

        if channel:
            expr_str = f"op('{src_path}')['{channel}']"
        else:
            expr_str = f"op('{src_path}')"

        try:
            getattr(dst.par, param_name).expr = expr_str
            results.append(f"{dst_path}.par.{param_name}.expr = \"{expr_str}\"")
        except Exception as e:
            errors.append(f"expression[{i}]: {e}")

    result = {"ok": len(errors) == 0, "wired": results}
    if errors:
        result["errors"] = errors
    return result


# ---------------------------------------------------------------------------
# DAT Read / Write / Edit Tools
# ---------------------------------------------------------------------------

def handle_read_dat(args):
    """Read text content from a DAT operator."""
    path = args.get('path', '')
    if not path:
        return {"error": "path is required"}

    target = op(path)
    if target is None:
        return {"error": f"Operator not found: {path}"}
    if target.family != 'DAT':
        return {"error": f"Not a DAT: {path} (family={target.family})"}

    text = target.text
    lines = text.split('\n')
    total = len(lines)

    offset = args.get('offset')
    limit = args.get('limit')

    start = max(0, int(offset) - 1) if offset is not None else 0
    end = start + int(limit) if limit is not None else total
    selected = lines[start:end]

    # Format with line numbers (cat -n style): "     1\tcontent"
    width = len(str(start + len(selected)))
    numbered = '\n'.join(
        f'{str(start + i + 1).rjust(width)}\t{line}'
        for i, line in enumerate(selected)
    )

    _read_paths.add(target.path)

    return {
        "path": target.path,
        "type": target.type,
        "lines": total,
        "content": numbered,
    }


def handle_write_dat(args):
    """Overwrite full text content of a DAT, or create a new TextDAT."""
    path = args.get('path', '')
    content = args.get('content', '')
    if not path:
        return {"error": "path is required"}

    target = op(path)

    if target is None:
        # Create a new TextDAT under the parent (no read required)
        parts = path.rsplit('/', 1)
        if len(parts) != 2 or not parts[0]:
            return {"error": f"Invalid path for creation: {path}"}
        parent_path, dat_name = parts
        parent = op(parent_path)
        if parent is None:
            return {"error": f"Parent not found: {parent_path}"}
        target = parent.create(textDAT, dat_name)
        target.text = content
        _read_paths.add(target.path)  # mark as known after creation
        return {
            "path": target.path,
            "created": True,
            "lines": content.count('\n') + 1,
        }

    if target.family != 'DAT':
        return {"error": f"Not a DAT: {path} (family={target.family})"}

    # Enforce read-before-write for existing DATs
    if target.path not in _read_paths:
        return {"error": f"You must use the 'read' tool on {path} before overwriting it. This prevents accidental data loss."}

    target.text = content
    return {
        "path": target.path,
        "lines": content.count('\n') + 1,
    }


def handle_edit_dat(args):
    """Find and replace text within a DAT operator."""
    path = args.get('path', '')
    old_string = args.get('old_string', '')
    new_string = args.get('new_string', '')
    replace_all = args.get('replace_all', False)

    if not path:
        return {"error": "path is required"}
    if not old_string:
        return {"error": "old_string is required"}

    target = op(path)
    if target is None:
        return {"error": f"Operator not found: {path}"}
    if target.family != 'DAT':
        return {"error": f"Not a DAT: {path} (family={target.family})"}

    # Enforce read-before-write
    if target.path not in _read_paths:
        return {"error": f"You must use the 'read' tool on {path} before editing it. This prevents accidental data loss."}

    text = target.text
    count = text.count(old_string)

    if count == 0:
        return {"error": f"old_string not found in {path}"}
    if count > 1 and not replace_all:
        return {"error": f"old_string found {count} times in {path} — use replace_all or provide more context"}

    # Find the position of the first match to report context
    match_pos = text.index(old_string)
    match_line = text[:match_pos].count('\n')  # 0-indexed line of match

    if replace_all:
        target.text = text.replace(old_string, new_string)
    else:
        target.text = text.replace(old_string, new_string, 1)

    # Show context around the edit (cat -n style)
    result_lines = target.text.split('\n')
    total = len(result_lines)
    new_line_count = new_string.count('\n') + 1
    ctx_start = max(0, match_line - 3)
    ctx_end = min(total, match_line + new_line_count + 3)
    width = len(str(ctx_end))
    preview = '\n'.join(
        f'{str(ctx_start + i + 1).rjust(width)}\t{line}'
        for i, line in enumerate(result_lines[ctx_start:ctx_end])
    )

    return {
        "path": target.path,
        "replacements": count if replace_all else 1,
        "lines": total,
        "preview": preview,
    }


def handle_list_ops(args):
    """List all operators under a container."""
    path = args.get('path', '')
    family_filter = args.get('family', '').upper()
    pattern = args.get('pattern', '')
    if not path:
        return {"error": "path is required"}

    container = op(path)
    if container is None:
        return {"error": f"Operator not found: {path}"}

    import fnmatch
    ops = []
    try:
        for child in container.children:
            if family_filter and child.family != family_filter:
                continue
            if pattern and not fnmatch.fnmatch(child.name, pattern):
                continue
            info = {"name": child.name, "type": child.type, "family": child.family}
            # Add family-specific summary info
            try:
                if child.family == 'TOP':
                    info["resolution"] = [child.width, child.height]
                elif child.family == 'CHOP':
                    info["channels"] = child.numChans
                    info["samples"] = child.numSamples
                elif child.family == 'DAT':
                    info["lines"] = child.text.count('\n') + 1
                elif child.family == 'SOP':
                    info["points"] = child.numPoints
                    info["prims"] = child.numPrims
                elif child.family == 'COMP':
                    info["children"] = len(child.children)
            except Exception:
                pass
            # Flag errors
            try:
                if child.errors():
                    info["hasErrors"] = True
            except Exception:
                pass
            ops.append(info)
    except Exception as e:
        return {"error": str(e)}

    return {"path": path, "ops": sorted(ops, key=lambda o: o['name'])}


def handle_op_docs(args):
    """Look up documentation for a TD operator type."""
    import td as _td
    import fnmatch as _fnmatch

    type_arg = args.get('type', '')
    family_filter = args.get('family', '').upper()
    par_filter = args.get('filter', '').lower()

    if not type_arg:
        return {"error": "type is required"}

    # --- List all available type constants ---
    if type_arg == 'list_types':
        families = ('CHOP', 'TOP', 'SOP', 'DAT', 'COMP', 'MAT')
        result = {}
        for fam in families:
            if family_filter and fam != family_filter:
                continue
            types = sorted(name for name in dir(_td) if name.endswith(fam) and name != fam)
            if types:
                result[fam] = types
        return {"types": result}

    # --- Resolve the operator type ---
    op_type = None
    source = None

    # Try as a type constant first (e.g. 'glslTOP')
    if hasattr(_td, type_arg):
        op_type = getattr(_td, type_arg)
        source = type_arg
    else:
        # Try as an operator path
        target = op(type_arg)
        if target is not None:
            op_type = target.OPType
            source = f"{type_arg} ({target.type}, {target.family})"
        else:
            # Fuzzy search: find type constants containing the query
            query = type_arg.lower()
            matches = [name for name in dir(_td)
                       if query in name.lower()
                       and any(name.endswith(f) for f in ('CHOP', 'TOP', 'SOP', 'DAT', 'COMP', 'MAT'))]
            if matches:
                return {"error": f"Type '{type_arg}' not found. Did you mean: {matches[:10]}"}
            return {"error": f"Type '{type_arg}' not found. Use type='list_types' to see available types."}

    # --- Create a temporary op, introspect it, destroy it ---
    root = _get_root()
    if root is None:
        return {"error": "Could not find project root"}

    tmp = None
    try:
        tmp = root.create(op_type, '__docs_tmp')

        # Gather parameters grouped by page
        pages = {}
        for p in tmp.pars():
            pg = str(p.page) if p.page else 'Other'
            # Common page included — has resolution, format, etc.
            if par_filter and par_filter not in p.name.lower() and par_filter not in p.label.lower():
                continue

            info = {"name": p.name, "label": p.label}

            # Default value
            if p.defaultExpr:
                info["default"] = p.defaultExpr
            else:
                info["default"] = _serialize(p.default)

            # Menu options
            if p.menuNames:
                info["menu"] = dict(zip(p.menuNames, p.menuLabels))

            # Parameter style (float, int, string, toggle, etc.)
            info["style"] = str(p.style)

            if pg not in pages:
                pages[pg] = []
            pages[pg].append(info)

        # Connector info
        connectors = {
            "inputs": len(tmp.inputConnectors),
            "outputs": len(tmp.outputConnectors),
        }

        result = {
            "type_constant": source,
            "op_type": tmp.type,
            "family": tmp.family,
            "connectors": connectors,
            "parameters": pages,
        }

        return result

    except Exception as e:
        return {"error": f"Failed to inspect {type_arg}: {e}"}
    finally:
        if tmp is not None:
            try:
                tmp.destroy()
            except Exception:
                pass


def _gather_network(container, family_filter='', include_defaults=False):
    """Gather operator data from a container for network rendering."""
    children = list(container.children)
    if family_filter:
        children = [c for c in children if c.family == family_filter]

    child_set = set(c.path for c in children)
    child_by_path = {c.path: c for c in children}

    # Group by family
    by_family = {}
    for c in children:
        by_family.setdefault(c.family, []).append(c)

    # Build edges
    edges = []
    for c in children:
        try:
            for inp in c.inputs:
                if inp and inp.path in child_set:
                    is_fb = (c.family == 'TOP' and c.type == 'feedback')
                    edges.append((inp.path, c.path, is_fb))
        except Exception:
            pass

    # Build node info
    nodes = {}
    for c in children:
        info = {"name": c.name, "type": c.type, "family": c.family}
        # Family-specific label extras
        try:
            if c.family == 'TOP':
                info["detail"] = f"{c.width}x{c.height}"
            elif c.family == 'CHOP':
                chans = []
                for i in range(min(c.numChans, 4)):
                    ch = c[i]
                    chans.append(f"{ch.name}={ch[0]:.2f}")
                if c.numChans > 4:
                    chans.append(f"+{c.numChans-4}")
                info["detail"] = ", ".join(chans)
            elif c.family == 'SOP':
                info["detail"] = f"{c.numPoints}pts {c.numPrims}prims"
            elif c.family == 'COMP':
                info["detail"] = f"{len(c.children)} children"
        except Exception:
            pass
        # Errors
        try:
            if c.errors():
                info["error"] = True
        except Exception:
            pass
        # Non-default params
        params = []
        for p in c.pars():
            pg = str(p.page) if p.page else ''
            if pg == 'Common' or p.name == 'pageindex':
                continue
            # Only when the parameter is actually in expression mode. A par
            # switched back to a constant keeps its old expression text, and
            # reporting that as live makes the map lie about the network.
            if p.expr and 'EXPRESSION' in str(p.mode).upper():
                params.append((p.name, p.expr, True))
            elif include_defaults or p.val != p.default:
                if not include_defaults and p.val == p.default:
                    continue
                params.append((p.name, str(p.val), False))
        info["params"] = params
        info["pos"] = (c.nodeX, c.nodeY)
        nodes[c.path] = info

    return children, child_set, child_by_path, by_family, edges, nodes


def _render_dot(container_path, children, child_set, child_by_path, by_family, edges, nodes):
    """Render network as DOT graph (text only, not intended for rendering)."""

    def _node_id(name):
        return name.replace('-', '_').replace(' ', '_').replace('.', '_')

    def _escape(s):
        return s.replace('"', '\\"').replace('<', '\\<').replace('>', '\\>')

    lines = []
    lines.append('digraph network {')
    lines.append('    rankdir=LR;')

    # Group into subgraphs by family
    for fam in ('TOP', 'CHOP', 'SOP', 'DAT', 'COMP', 'MAT'):
        ops = by_family.get(fam, [])
        if not ops:
            continue

        lines.append(f'    subgraph cluster_{fam} {{')
        lines.append(f'        label="{fam}";')

        for o in sorted(ops, key=lambda x: x.name):
            info = nodes[o.path]
            nid = _node_id(info['name'])

            # Build label: name + type + position + detail + key params
            x, y = info.get('pos', (0, 0))
            label_parts = [info['name'], f"{info['type']}/{info['family']} @({x},{y})"]
            if 'detail' in info:
                label_parts.append(info['detail'])
            for pname, pval, is_expr in info['params'][:4]:
                if is_expr:
                    short = pval if len(pval) <= 30 else pval[:27] + '...'
                    label_parts.append(f"{pname} := {short}")
                else:
                    label_parts.append(f"{pname} = {pval}")
            if len(info['params']) > 4:
                label_parts.append(f"+{len(info['params'])-4} more")

            label = _escape('\\n'.join(label_parts))
            error_mark = ' [ERROR]' if info.get('error') else ''
            lines.append(f'        {nid} [label="{label}{error_mark}"];')

        lines.append('    }')

    # Edges
    for src_path, dst_path, is_fb in edges:
        src_id = _node_id(nodes[src_path]['name'])
        dst_id = _node_id(nodes[dst_path]['name'])
        if is_fb:
            lines.append(f'    {src_id} -> {dst_id} [label="feedback"];')
        else:
            lines.append(f'    {src_id} -> {dst_id};')

    lines.append('}')
    return '\n'.join(lines)


def handle_network_map(args):
    """Render a text map of the operator network."""
    path = args.get('path', '')
    family_filter = args.get('family', '').upper()
    include_defaults = args.get('include_defaults', False)

    if not path:
        return {"error": "path is required"}

    container = op(path)
    if container is None:
        return {"error": f"Operator not found: {path}"}

    data = _gather_network(container, family_filter, include_defaults)
    children, child_set, child_by_path, by_family, edges, nodes = data

    if not children:
        return {"path": path, "map": "(empty)"}

    # Generate DOT source
    dot_src = _render_dot(path, *data)

    # Build text map: DOT source + parameters
    lines = []
    lines.append(dot_src)
    lines.append("")
    lines.append("## Parameters (non-default)")
    lines.append("")
    for c in sorted(children, key=lambda x: x.name):
        info = nodes[c.path]
        if info['params']:
            lines.append(f"**{info['name']}** ({info['type']}/{info['family']})")
            for pname, pval, is_expr in info['params']:
                if is_expr:
                    lines.append(f"  {pname} := `{pval}`")
                else:
                    lines.append(f"  {pname} = {pval}")
            lines.append("")

    return {"path": path, "map": "\n".join(lines)}


def _serialize(obj):
    """Convert TD objects to JSON-serializable form."""
    if obj is None:
        return None
    if isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_serialize(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _serialize(v) for k, v in obj.items()}
    # TD-specific types
    try:
        if hasattr(obj, 'path'):  # OP
            return f"<{obj.type} {obj.path}>"
        if hasattr(obj, 'name') and hasattr(obj, 'vals'):  # Channel
            return {"name": obj.name, "value": float(obj[0])}
    except Exception:
        pass
    return str(obj)


# ---------------------------------------------------------------------------
# Tool Dispatch
# ---------------------------------------------------------------------------
TOOL_HANDLERS = {
    'run': handle_td_run,
    'inspect': handle_inspect_op,
    'set': handle_set,
    'create': handle_create,
    'wire': handle_wire,
    'observe': handle_observe,
    'render': handle_render,
    'read': handle_read_dat,
    'write': handle_write_dat,
    'edit': handle_edit_dat,
    'list': handle_list_ops,
    'docs': handle_op_docs,
    'map': handle_network_map,
}


# ---------------------------------------------------------------------------
# JSON-RPC / MCP Protocol Handler
# ---------------------------------------------------------------------------

# Session management
_session_id = None
_read_paths = set()   # tracks DAT paths that have been read (for read-before-write)


def _get_session_id():
    global _session_id
    if _session_id is None:
        _session_id = str(_uuid.uuid4())
    return _session_id


def _jsonrpc_response(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _jsonrpc_error(req_id, code, message):
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }


def _handle_one(msg):
    """Process a single JSON-RPC message. Returns dict or None (for notifications)."""
    req_id = msg.get('id')
    method = msg.get('method', '')
    params = msg.get('params', {})

    # Notifications have no id — no response expected
    is_notification = req_id is None

    if method == 'initialize':
        return _jsonrpc_response(req_id, {
            "protocolVersion": MCP_VERSION,
            "serverInfo": SERVER_INFO,
            "capabilities": CAPABILITIES,
        })

    elif method == 'notifications/initialized':
        return None  # notification, no response

    elif method == 'tools/list':
        return _jsonrpc_response(req_id, {"tools": TOOLS})

    elif method == 'tools/call':
        tool_name = params.get('name', '')
        tool_args = params.get('arguments', {})

        handler = TOOL_HANDLERS.get(tool_name)
        if handler is None:
            return _jsonrpc_error(req_id, -32601, f"Unknown tool: {tool_name}")

        try:
            tool_result = handler(tool_args)

            # Build content blocks
            content = []

            # Extract embedded images before serializing
            images = []
            if isinstance(tool_result, dict):
                # observe tool image
                obs_b64 = tool_result.pop('_observe_b64', None)
                obs_mime = tool_result.pop('_observe_mime', None)
                obs_top = tool_result.pop('_observe_top', None)
                if obs_b64:
                    if obs_top:
                        images.append(("text", json.dumps({"source": obs_top})))
                    images.append(("image", obs_b64, obs_mime or "image/gif"))

            # Add text content (skip empty results)
            if tool_result:
                content.append({
                    "type": "text",
                    "text": json.dumps(tool_result, indent=2),
                })

            # Attach any embedded images
            for img in images:
                if img[0] == "text":
                    content.append({"type": "text", "text": img[1]})
                elif img[0] == "image":
                    content.append({
                        "type": "image",
                        "data": img[1],
                        "mimeType": img[2],
                    })

            return _jsonrpc_response(req_id, {"content": content})
        except Exception as e:
            return _jsonrpc_response(req_id, {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"error": str(e)}),
                    }
                ],
                "isError": True,
            })

    elif method == 'ping':
        return _jsonrpc_response(req_id, {})

    elif is_notification:
        return None  # unknown notification, ignore

    else:
        return _jsonrpc_error(req_id, -32601, f"Method not found: {method}")


def _handle_request(body):
    """Process JSON-RPC body (single or batch). Returns (responses_list, is_initialize)."""
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return [_jsonrpc_error(None, -32700, "Parse error")], False

    # Support batched requests (array of messages)
    if isinstance(parsed, list):
        messages = parsed
    else:
        messages = [parsed]

    is_initialize = any(m.get('method') == 'initialize' for m in messages)
    responses = []

    for msg in messages:
        result = _handle_one(msg)
        if result is not None:
            responses.append(result)

    return responses, is_initialize


# ---------------------------------------------------------------------------
# Web Server DAT Callbacks
# ---------------------------------------------------------------------------

def onHTTPRequest(webServerDAT, request, response):
    """
    Handle incoming HTTP requests from the Web Server DAT.
    MCP Streamable HTTP: POST /mcp with JSON-RPC body.
    """
    uri = request.get('uri', '')
    method = request.get('method', 'GET')

    def _respond(status, reason, data='', content_type='application/json', **extra):
        response['statusCode'] = status
        response['statusReason'] = reason
        response['data'] = data
        response['content-type'] = content_type
        # CORS headers
        response['Access-Control-Allow-Origin'] = '*'
        response['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
        response['Access-Control-Allow-Headers'] = 'Content-Type, Accept, Mcp-Session-Id'
        response['Access-Control-Expose-Headers'] = 'Mcp-Session-Id'
        for k, v in extra.items():
            response[k] = v
        return response

    # CORS preflight
    if method == 'OPTIONS':
        return _respond(204, 'No Content', content_type='text/plain')

    # Health check
    if uri == '/health' or (uri == '/' and method == 'GET'):
        return _respond(200, 'OK', json.dumps({"status": "ok", "server": "touchdesigner"}))

    # MCP endpoint - DELETE (session termination)
    if uri == '/mcp' and method == 'DELETE':
        return _respond(200, 'OK')

    # MCP endpoint - GET (SSE stream — not supported, return 405)
    if uri == '/mcp' and method == 'GET':
        return _respond(405, 'Method Not Allowed', json.dumps({"error": "SSE not supported, use POST"}))

    # MCP endpoint - POST
    if uri == '/mcp' and method == 'POST':
        body = request.get('data', '')
        responses, is_initialize = _handle_request(body)

        if len(responses) == 0:
            return _respond(202, 'Accepted', content_type='text/plain')

        data = json.dumps(responses[0]) if len(responses) == 1 else json.dumps(responses)
        extra = {}
        if is_initialize:
            extra['Mcp-Session-Id'] = _get_session_id()
        return _respond(200, 'OK', data, **extra)

    # 404 for everything else
    return _respond(404, 'Not Found', json.dumps({"error": "Not found"}))
