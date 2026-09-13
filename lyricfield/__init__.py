"""lyricfield — a lyric-video system built on TouchDesigner.

The repo is the source of truth. TouchDesigner holds only a thin shell (a Script
TOP, a few DATs and the render chain); behaviour lives in `td/field_callbacks.py`
and is pushed in by `sync`. That inverts how the project started, when everything
lived inside a binary .toe that could not be diffed, reviewed or recovered.

Layout:
    config.py       every tunable, with the constraints between them encoded
    cues.py         the per-word cue table (TSV, hand-editable)
    transcribe.py   Groq Whisper -> word-level cues
    analysis.py     instrumental structure: silences, kick entry, tempo
    td_client.py    JSON-RPC client for the TD web server
    sync.py         push repo -> TD, and pull cue tables back out
    render.py       capture, container validation, stem muxing, still sampling
    ui/             local control UI
    td/             code that runs *inside* TouchDesigner

Lyric text is always user-supplied — typed in the UI, imported, or transcribed.
None is bundled with the source.
"""

__version__ = "0.1.0"

__all__ = [
    "analysis",
    "config",
    "cues",
    "render",
    "sync",
    "td_client",
    "transcribe",
]
