# lyricfield

A lyric-video system: a dense character grid where the song's own words sit dim
and drifting, brighten in place on cue, and respond to the beat as light.
TouchDesigner renders it; everything that decides how it behaves lives here.

## Why the code is here and not in the .toe

This began as a TouchDesigner project built live through MCP calls. Every change
was a tool call, the logic lived in Text DATs inside a binary `.toe`, and that
file could not be diffed, reviewed, or recovered when the app crashed. Several
real bugs survived for multiple versions because nothing could be tested outside
the running app.

Now the repo is the source of truth. TouchDesigner keeps a thin shell — a Script
TOP, a few DATs, the render chain — and `sync` pushes behaviour into it.

## Setup

```bash
pip install -r ../requirements.txt      # numpy, fastapi, uvicorn, pydantic
export GROQ_API_KEY=...                 # for transcription
cp ../data/config.example.toml ../data/config.toml
```

`ffmpeg` and `ffprobe` must be on PATH. TouchDesigner must be running with the
`td_mcp_server` component listening on :9988.

## Use

```bash
python -m lyricfield.ui.server           # http://127.0.0.1:8765
```

Or from the command line:

```bash
python -m lyricfield.analysis    no_vocals.wav          # structure of the track
python -m lyricfield.transcribe  vocals.wav -o ../data/cues.tsv
```

Typical flow: point at the stems → **Analyse** → **Transcribe vocals** → fix any
misheard words in the cue table → **Push to TD** → **Render** → **Sample stills**.

## Layout

| module | responsibility |
|---|---|
| `config.py` | every tunable, plus the constraints *between* them |
| `cues.py` | per-word cue table (TSV), validation |
| `transcribe.py` | Groq Whisper → word-level cues |
| `analysis.py` | silences, kick entry, tempo, beat phase |
| `td_client.py` | JSON-RPC client for the TD web server |
| `sync.py` | push repo → TD; pull cue tables back out |
| `render.py` | capture, container validation, stem muxing, stills |
| `ui/` | local control UI |
| `td/field_callbacks.py` | runs **inside** TouchDesigner |

## Things that are easy to get wrong

These are encoded as checks in `Config.validate()` and `CueTable.problems()`
because each one shipped as a real defect.

**Brightness stacks.** `spark_peak` and `ripple_lift` add on top of the glow
before reaching the output. Set to 0.75/0.40 they measured **0.99** at
`/project1/out` — visually identical to a cued word, which is the one thing
reserved for 1.0. Change them together and re-measure at the output.

**Measure at the output, never upstream.** A bloom branch using a Level TOP's
black level went *negative* (a black level remaps, it does not clamp), and the
blur spread that negative field frame-wide, subtracting ~0.23 from everything.
Every metric taken on the Script TOP looked perfect while the render was wrong.

**The band must fill the frame.** `band` rows inside `vrows` — when the
oscilloscope was removed, `band` stayed at 14 of 24 and left 480px of dead black
at the bottom of frame for three versions.

**TD's render audio drifts.** Its AudioFileOut records in wall-clock time while
cooking runs slower than real time, so the WAV ends up longer than the picture.
`render.py` always discards it and muxes the original stems.

**TD lies about finishing.** The MP4 is reported complete while the moov atom is
still being written; one render failed remuxing with `moov atom not found` after
the PNG frames had already been deleted. `wait_for_container` requires a stable
size *and* a successful ffprobe parse.

**TD stalls on save.** The Script TOP runs `CookLevel.ALWAYS` and blocks the web
server thread, so saves routinely hang for one to three minutes and then succeed.
`sync.save_project` quiesces first and treats a timeout as "wait and re-check".

## Lyrics

Lyric text is always user-supplied — typed in the UI, imported, or transcribed
from a vocal stem. None is bundled with the source, and `data/cues.tsv` is
gitignored.
