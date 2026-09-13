"""lyricfield — a music-video system built on TouchDesigner.

Ingest a song, choose the kind of video to make, and the system renders it. The
ingest half is shared by every video type: separate the stems, measure the
track's structure, transcribe the words. What differs is the renderer.

The repo is the source of truth. TouchDesigner holds only a thin shell (a Script
TOP, a few DATs and the render chain); behaviour lives in the video type and is
pushed in by `sync`. That inverts how the project started, when everything lived
inside a binary .toe that could not be diffed, reviewed or recovered.

Layout:
    config.py       a song's config: track facts + video type + that type's params
    sections.py     the sectioned-dataclass/TOML machinery both of those share
    cues.py         the per-word cue table (TSV, hand-editable)
    separate.py     Demucs stem separation
    transcribe.py   Groq Whisper -> word-level cues
    analysis.py     instrumental structure: silences, kick entry, tempo
    pipeline.py     prepare(): separate -> analyse -> transcribe, resumable
    styles.py       named presets of one type's params, with video previews
    workspace.py    one folder per song
    td_client.py    JSON-RPC client for the TD web server
    sync.py         push repo -> TD, and pull cue tables back out
    render.py       capture, container validation, stem muxing, still sampling
    ui/             local control UI
    types/          the video types, one package each

Lyric text is always user-supplied — typed in the UI, imported, or transcribed.
None is bundled with the source.
"""

__version__ = "0.1.0"

__all__ = [
    "analysis",
    "config",
    "cues",
    "pipeline",
    "render",
    "separate",
    "styles",
    "sync",
    "td_client",
    "transcribe",
    "types",
    "workspace",
]
