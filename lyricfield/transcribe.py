"""Groq Whisper transcription -> per-word cue table.

Hand-timing a cue table is the single most tedious part of building one of these;
a hundred words means a hundred timestamps read off a waveform. Whisper returns
word-level timestamps directly, and Groq runs it fast enough to be interactive.

Transcribe the VOCAL stem, not the mix -- isolated vocals give markedly better
word boundaries, and the stems already exist because the source was separated.

Output is a `CueTable`; line numbers come from Whisper's own segment boundaries,
which track sung phrases well. The result is a starting point: expect to fix a
few words by hand in the TSV afterwards, which is exactly why it is a TSV.

Stdlib only -- multipart is assembled by hand rather than pulling in `requests`.
"""

from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path

from .cues import Cue, CueTable

GROQ_URL = "https://api.groq.com/openai/v1/audio/transcriptions"
USER_AGENT = "lyricfield/0.1 (+https://github.com/adityasuyash/touchdesigner-mcp)"
DEFAULT_MODEL = "whisper-large-v3"
MAX_UPLOAD_MB = 24          # Groq rejects larger; we downconvert below this


class TranscribeError(RuntimeError):
    pass


@dataclass
class Word:
    word: str
    start: float
    end: float


KEY_FILE = Path.home() / ".config" / "lyricfield" / "groq.key"


def store_api_key(key: str, path: Path = KEY_FILE) -> Path:
    """Persist the key once, readable only by its owner.

    A credential the user has supplied once should never be asked for again, so
    the UI field writes through to here rather than holding the key for the life
    of the page.
    """
    key = key.strip()
    if not key:
        raise TranscribeError("refusing to store an empty key")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(key + "\n")
    path.chmod(0o600)
    return path


def stored_api_key(path: Path = KEY_FILE) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def api_key(explicit: str | None = None) -> str:
    """Explicit argument, then environment, then the stored key file."""
    key = (explicit or "").strip() or os.environ.get("GROQ_API_KEY", "").strip() \
        or stored_api_key()
    if not key:
        raise TranscribeError(
            f"no Groq API key. Save one with `python -m lyricfield.transcribe "
            f"--set-key <key>` (stored at {KEY_FILE}), set GROQ_API_KEY in the "
            f"environment, or enter it once in the UI."
        )
    return key


# How much audio to keep in front of the first singing. Whisper is markedly
# worse at the start of a file, and a long quiet intro is what triggers it: on
# one song a 6.6s instrumental lead-in made it drop the entire opening couplet
# and hang the second line's words on the first line's timestamps, so the cue
# count and coverage both looked healthy.
#
# Measured on that song, transcribing the vocal stem four ways:
#
#   whole file, 64k / 128k ..... opening couplet lost, both times
#   1s of silence prepended .... still lost (and see the adelay note below)
#   trimmed to the first word .. recovered, 379 words
#
# Padding made it worse, trimming fixed it, so the upload starts where the
# singing starts. The lead-in is small on purpose: half a second of silence was
# enough to send the model off the rails again (321 words and an "uploaded by"
# hallucination), which is the same first-file-second weakness seen from the
# other side.
LEAD_IN = 0.1

# Below this there is no intro worth trimming and no reason to re-measure.
MIN_TRIM = 1.0


def _upload_start(path: Path) -> float:
    """Where to begin the upload: just before the first singing, or zero."""
    try:
        from . import analysis
        entry = analysis.vocal_entry(path)
    except Exception:      # measurement is an optimisation, never a hard failure
        return 0.0
    return round(max(0.0, entry - LEAD_IN), 2) if entry >= MIN_TRIM else 0.0


def _compress(path: Path, start: float = 0.0) -> Path:
    """Whisper only needs 16kHz mono, so the upload stays small.

    The bitrate is generous rather than minimal: a four-minute 16kHz mono file
    is far below the 24MB limit even at 128k, and thrift here costs
    intelligibility on quiet, breathy singing -- exactly where transcription is
    already weakest.

    `start` trims the silent lead-in; see LEAD_IN. Note that seeking is what
    trims, not a filter: `adelay` with a single delay value moves only the first
    channel, and the downmix to mono below then restores the original timing
    from the untouched second channel -- the shift silently vanishes while the
    caller still corrects for it, putting every word a second out.
    """
    out = Path(tempfile.gettempdir()) / f"lyricfield_{uuid.uuid4().hex}.mp3"
    seek = ["-ss", f"{start}"] if start else []
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *seek, "-i", str(path),
         "-ac", "1", "-ar", "16000", "-b:a", "128k", str(out)],
        check=True,
    )
    return out


def _multipart(fields: list[tuple[str, str]], file_field: str,
               file_path: Path) -> tuple[bytes, str]:
    boundary = f"----lyricfield{uuid.uuid4().hex}"
    crlf = b"\r\n"
    buf = bytearray()
    for name, value in fields:
        buf += b"--" + boundary.encode() + crlf
        buf += f'Content-Disposition: form-data; name="{name}"'.encode() + crlf + crlf
        buf += value.encode() + crlf
    ctype = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    buf += b"--" + boundary.encode() + crlf
    buf += (
        f'Content-Disposition: form-data; name="{file_field}"; '
        f'filename="{file_path.name}"'.encode() + crlf
    )
    buf += f"Content-Type: {ctype}".encode() + crlf + crlf
    buf += file_path.read_bytes() + crlf
    buf += b"--" + boundary.encode() + b"--" + crlf
    return bytes(buf), f"multipart/form-data; boundary={boundary}"


def transcribe_words(audio: str | Path, key: str | None = None,
                     model: str = DEFAULT_MODEL,
                     language: str | None = None,
                     prompt: str | None = None,
                     timeout: float = 300.0) -> tuple[list[Word], list[tuple[float, float]]]:
    """Returns (words, segment_spans). Segment spans become line boundaries."""
    src = Path(audio)
    if not src.exists():
        raise TranscribeError(f"no such file: {src}")

    # Always re-encode, so the lead-in trim is applied consistently and the
    # offset below is always the right one to add back.
    offset = _upload_start(src)
    tmp = _compress(src, offset)
    src = tmp
    # MAX_UPLOAD_MB was declared and never consulted, so an over-long track got
    # a raw HTTP error from Groq instead of a sentence explaining it.
    size_mb = src.stat().st_size / 1048576
    if size_mb > MAX_UPLOAD_MB:
        raise TranscribeError(
            f"the vocal stem compresses to {size_mb:.1f}MB, over the "
            f"{MAX_UPLOAD_MB}MB upload limit (about {MAX_UPLOAD_MB * 60 / 16:.0f} "
            f"minutes of audio). Split the track and transcribe the parts.")

    try:
        fields = [
            ("model", model),
            ("response_format", "verbose_json"),
            ("timestamp_granularities[]", "word"),
            ("timestamp_granularities[]", "segment"),
        ]
        if language:
            fields.append(("language", language))
        if prompt:
            # a prompt containing the known lyrics markedly improves proper nouns
            fields.append(("prompt", prompt[:1000]))

        body, ctype = _multipart(fields, "file", src)
        req = urllib.request.Request(
            GROQ_URL,
            data=body,
            headers={
                "Authorization": f"Bearer {api_key(key)}",
                "Content-Type": ctype,
                # Cloudflare fronts the Groq API and rejects urllib's default
                # User-Agent outright, as 403 "error code: 1010" -- which reads
                # exactly like a rejected key and sends you hunting the wrong
                # bug. Identify the client honestly and it passes.
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise TranscribeError(f"Groq returned {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise TranscribeError(f"cannot reach Groq: {e}") from e
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)

    # Put the trimmed lead-in back, so every timestamp still refers to the song
    # rather than to the upload.
    words = [
        Word(w["word"].strip(),
             float(w["start"]) + offset,
             float(w["end"]) + offset)
        for w in payload.get("words", [])
        if w.get("word", "").strip()
    ]
    spans = [
        (float(s["start"]) + offset, float(s["end"]) + offset)
        for s in payload.get("segments", [])
    ]
    if not words:
        raise TranscribeError(
            "Groq returned no word timestamps. Check the model supports "
            "timestamp_granularities, and that the stem is not silent."
        )
    return words, spans


def words_to_cues(words: list[Word], spans: list[tuple[float, float]],
                  gap_break: float = 0.9) -> CueTable:
    """Assign line numbers. Whisper's segments track sung phrases, so prefer them;
    fall back to splitting on inter-word gaps when segments are absent."""
    cues: list[Cue] = []
    if spans:
        for w in words:
            line = 1
            for i, (s, e) in enumerate(spans):
                if s - 0.01 <= w.start <= e + 0.01:
                    line = i + 1
                    break
            else:
                line = min(range(len(spans)),
                           key=lambda i: abs(spans[i][0] - w.start)) + 1
            cues.append(Cue(w.word, round(w.start, 2), line))
    else:
        line = 1
        prev_end = None
        for w in words:
            if prev_end is not None and w.start - prev_end > gap_break:
                line += 1
            cues.append(Cue(w.word, round(w.start, 2), line))
            prev_end = w.end

    # renumber so lines are 1..N contiguous in time
    order = {ln: i + 1 for i, ln in enumerate(sorted({c.line for c in cues}))}
    return CueTable([Cue(c.word, c.start, order[c.line]) for c in cues])


def transcribe_to_cues(audio: str | Path, key: str | None = None,
                       model: str = DEFAULT_MODEL, language: str | None = None,
                       prompt: str | None = None) -> CueTable:
    words, spans = transcribe_words(audio, key=key, model=model,
                                    language=language, prompt=prompt)
    return words_to_cues(words, spans)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Transcribe a vocal stem to a cue table.")
    ap.add_argument("audio", nargs="?", help="vocal stem (not the full mix)")
    ap.add_argument("--set-key", dest="set_key", default=None, metavar="KEY",
                    help="store the Groq key once and exit")
    ap.add_argument("-o", "--out", default="data/cues.tsv")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--language", default=None, help="ISO code, e.g. en, hi")
    ap.add_argument("--prompt", default=None,
                    help="known lyrics; improves proper nouns and spelling")
    a = ap.parse_args(argv)

    if a.set_key:
        path = store_api_key(a.set_key)
        print(f"key stored at {path} (owner-only). No need to enter it again.")
        return 0
    if not a.audio:
        ap.error("audio is required unless --set-key is given")

    table = transcribe_to_cues(a.audio, model=a.model,
                               language=a.language, prompt=a.prompt)
    table.save(a.out)
    lines = table.lines
    print(f"{len(table.cues)} words across {len(lines)} lines -> {a.out}")
    for p in table.problems():
        print(f"  warning: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
