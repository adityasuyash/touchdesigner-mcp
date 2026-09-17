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
import re
import os
import subprocess
import tempfile
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from difflib import SequenceMatcher

import numpy as np
from pathlib import Path

from .cues import Cue, CueTable

# What counts as a word in the lyrics someone types. Letters and digits in any
# script, plus the apostrophes and hyphens that live inside words.
_WORDS = re.compile(r"[^\s]+")

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


# What the model will accept, and what the UI offers. Here rather than in the
# server because it is a fact about the transcription API, the way
# `/api/browse` owns its extension sets.
#
# "Language is worth more than any audio setting" is measured, not a slogan:
# auto-detection gave 43 words on a Hindi track where `language="hi"` gave 121,
# from identical audio. So the likely ones come first, by name, and a typed
# code still works -- this list is what the dropdown shows, not a gate.
LANGUAGES: tuple[tuple[str, str], ...] = (
    ("", "Detect automatically"),
    ("en", "English"),
    ("hi", "Hindi"),
    ("pa", "Punjabi"),
    ("ur", "Urdu"),
    ("ta", "Tamil"),
    ("te", "Telugu"),
    ("bn", "Bengali"),
    ("mr", "Marathi"),
    ("gu", "Gujarati"),
    ("kn", "Kannada"),
    ("ml", "Malayalam"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("de", "German"),
    ("it", "Italian"),
    ("pt", "Portuguese"),
    ("nl", "Dutch"),
    ("ru", "Russian"),
    ("uk", "Ukrainian"),
    ("pl", "Polish"),
    ("tr", "Turkish"),
    ("ar", "Arabic"),
    ("fa", "Persian"),
    ("he", "Hebrew"),
    ("id", "Indonesian"),
    ("ms", "Malay"),
    ("th", "Thai"),
    ("vi", "Vietnamese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("zh", "Chinese"),
    ("sv", "Swedish"),
    ("no", "Norwegian"),
    ("da", "Danish"),
    ("fi", "Finnish"),
    ("cs", "Czech"),
    ("el", "Greek"),
    ("ro", "Romanian"),
    ("hu", "Hungarian"),
    ("sw", "Swahili"),
    ("af", "Afrikaans"),
)


def language_payload() -> list[dict]:
    """The list as the UI needs it: code and name, detect first."""
    return [{"code": c, "name": n} for c, n in LANGUAGES]


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


def _compress(path: Path, start: float = 0.0,
              seconds: float | None = None) -> Path:
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
    span = ["-t", f"{seconds}"] if seconds else []
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *seek, *span, "-i", str(path),
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
                     timeout: float = 300.0,
                     window: tuple[float, float] | None = None,
                     ) -> tuple[list[Word], list[tuple[float, float]]]:
    """Returns (words, segment_spans). Segment spans become line boundaries.

    `window` transcribes one stretch of the file instead of all of it. The
    offset machinery below was already adding the lead-in trim back to every
    timestamp, so a window costs nothing more than a different seek.
    """
    src = Path(audio)
    if not src.exists():
        raise TranscribeError(f"no such file: {src}")

    # Always re-encode, so the lead-in trim is applied consistently and the
    # offset below is always the right one to add back.
    if window:
        offset, span = float(window[0]), float(window[1]) - float(window[0])
        tmp = _compress(src, offset, seconds=span)
    else:
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
            # Greedy, not sampled. Whisper's failure mode on a passage it
            # cannot make out is to repeat the last phrase it was sure of, and
            # sampling is what lets that run away: one song came back with
            # "आपको इस परिवार का प्रभाव करते हैं" transcribed twice at 0.02s
            # per word, 16 of its 121 cues invented inside 2.1 seconds. Nothing
            # downstream looked, so they shipped into the render.
            ("temperature", "0"),
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


# ------------------------------------------------- the words you already have

# Devanagari consonants to a rough Latin skeleton. This is NOT transliteration
# and is never displayed -- honest romanisation needs schwa deletion and would
# read wrong ("suna re piyaa"). It exists only so a sequence matcher can see
# that "सुन" and "sun" are the same word, which is a far lower bar.
_SKELETON = {
    'क': 'k', 'ख': 'k', 'ग': 'g', 'घ': 'g', 'ङ': 'n',
    'च': 'c', 'छ': 'c', 'ज': 'j', 'झ': 'j', 'ञ': 'n',
    'ट': 't', 'ठ': 't', 'ड': 'd', 'ढ': 'd', 'ण': 'n',
    'त': 't', 'थ': 't', 'द': 'd', 'ध': 'd', 'न': 'n',
    'प': 'p', 'फ': 'f', 'ब': 'b', 'भ': 'b', 'म': 'm',
    'य': 'y', 'र': 'r', 'ल': 'l', 'व': 'v', 'ळ': 'l',
    'श': 's', 'ष': 's', 'स': 's', 'ह': 'h',
    'क़': 'k', 'ख़': 'k', 'ग़': 'g', 'ज़': 'j', 'ड़': 'd', 'ढ़': 'd', 'फ़': 'f',
    'अ': 'a', 'आ': 'a', 'इ': 'i', 'ई': 'i', 'उ': 'u', 'ऊ': 'u',
    'ए': 'e', 'ऐ': 'e', 'ओ': 'o', 'औ': 'o', 'ऋ': 'r',
    # Anusvara and chandrabindu. A nasal is a consonant and carries real
    # information -- without these "कहाँ" reduces to 'k' while "kahaan"
    # reduces to 'kn', and two spellings of one word stop matching.
    'ं': 'n', 'ँ': 'n',
}

# Romanisations of the same sound that have to reduce alike. The aspirated
# digraphs pair with the single Devanagari letters above -- "bh" with भ, "ph"
# with फ -- and the rest are the ambiguities every Hinglish speaker spells both
# ways: saanwariya/saanvariya, zara/jara.
_DIGRAPHS = (("chh", "c"), ("ph", "f"), ("ch", "c"), ("sh", "s"), ("th", "t"),
             ("kh", "k"), ("gh", "g"), ("bh", "b"), ("dh", "d"), ("jh", "j"),
             ("ck", "k"), ("x", "ks"), ("w", "v"), ("z", "j"), ("q", "k"))

# Latin letters that carry no information for matching across a transliteration.
_THIN = str.maketrans("", "", "aeiouāīūʼ'`h")


def match_key(word: str) -> str:
    """A rough consonant skeleton, for lining two word sequences up.

    Used to compare a Devanagari transcript against romanised lyrics. Vowels go
    because transliteration disagrees about them constantly -- "piya"/"piyaa",
    "sun"/"sunn" -- while consonants survive. Never shown to anyone.
    """
    w = word.lower()
    # Digraphs first: they have to fold before `h` is stripped, or "bhai" and
    # "भाई" reduce differently.
    for a, b in _DIGRAPHS:
        w = w.replace(a, b)
    out = []
    for ch in w:
        if ch in _SKELETON:
            out.append(_SKELETON[ch])
        elif ch.isalnum() and ch.isascii():
            out.append(ch)
        # combining vowel signs, virama, punctuation and everything else drop
    key = "".join(out).translate(_THIN)
    # "sunn" and "sun" are one word spelled twice.
    squashed = "".join(c for i, c in enumerate(key) if i == 0 or c != key[i - 1])
    return squashed or word.lower()


def align_to_known(words: list[Word], known: str,
                   line_span: float = 3.0) -> CueTable:
    """The user's words, on the transcript's timings.

    Whisper is reliable about WHEN something is sung and unreliable about WHAT
    -- measured across three songs, its cues land within 0.07s of actual
    singing while inventing whole phrases. So take the timing from it and the
    text from the person who knows the song.

    Matched runs keep their transcribed time. Words the transcript missed are
    spread evenly between the anchors either side, which is the same thing
    `cues.cues_from_lines` does for a line. Lines come from the user's own
    breaks, which is strictly better than Whisper's segments: those are sung
    phrases and come back as one 32-word line on a sustained passage.
    """
    lines = [ln.strip() for ln in (known or "").splitlines()]
    lines = [ln for ln in lines if ln and not ln.startswith("#")]
    if not lines:
        raise TranscribeError("no known lyrics to align to")

    want: list[tuple[str, int]] = []
    for n, ln in enumerate(lines, 1):
        for w in _WORDS.findall(ln):
            want.append((w, n))
    if not want:
        raise TranscribeError("the known lyrics have no words in them")

    got = [w for w in words]
    a = [match_key(w) for w, _ in want]
    b = [match_key(w.word) for w in got]

    # Where the two sequences agree, take the transcript's clock.
    at: list[float | None] = [None] * len(want)
    for block in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(block.size):
            at[block.a + k] = got[block.b + k].start

    anchors = [i for i, t in enumerate(at) if t is not None]
    if not anchors:
        raise TranscribeError(
            "none of the known lyrics could be matched to the transcription. "
            "Check they are the right song, and that the language setting "
            "matches what was sung.")

    # ... and spread the rest between them. Before the first anchor and after
    # the last, keep going at the local pace rather than piling words onto one
    # instant.
    first, last = anchors[0], anchors[-1]
    step = _pace(at, anchors, line_span)
    for i in range(first - 1, -1, -1):
        at[i] = max(0.0, at[i + 1] - step)
    for i in range(last + 1, len(at)):
        at[i] = at[i - 1] + step
    for lo, hi in zip(anchors, anchors[1:]):
        if hi - lo < 2:
            continue
        gap = (at[hi] - at[lo]) / (hi - lo)
        for k in range(lo + 1, hi):
            at[k] = at[lo] + gap * (k - lo)

    return CueTable([Cue(w, round(float(t), 2), n)
                     for (w, n), t in zip(want, at)])


def _pace(at, anchors, fallback: float) -> float:
    """Seconds per word, from the anchors that exist."""
    if len(anchors) < 2:
        return fallback / 3.0
    span = at[anchors[-1]] - at[anchors[0]]
    return max(0.08, span / max(1, anchors[-1] - anchors[0]))


# Nobody sings faster than this. A run of words closer together than this is a
# decoder collapsing, not a vocal.
COLLAPSED = 0.05
COLLAPSED_RUN = 4


def drop_collapsed(words: list[Word],
                   closer_than: float = COLLAPSED,
                   run: int = COLLAPSED_RUN) -> list[Word]:
    """Throw away runs of words too close together to have been sung.

    Whisper answers a passage it cannot make out by repeating the last phrase
    it was sure of, and it stamps the repeat with whatever timestamps are
    left -- so the giveaway is not the words but the spacing. Measured on a
    real song: sixteen words inside 2.1 seconds, most of them 0.02s apart,
    which is fifty words a second.

    Dropping them rather than keeping them is right even though it loses
    whatever real word was there: an invented line is drawn on screen with
    total confidence, and a missing one leaves a gap the second pass can go
    back for.
    """
    if not words:
        return []
    out: list[Word] = []
    i, n = 0, len(words)
    while i < n:
        j = i + 1
        while j < n and words[j].start - words[j - 1].start < closer_than:
            j += 1
        if j - i >= run:
            i = j                       # the whole run goes
            continue
        out.append(words[i])
        i += 1
    return out


def drop_repeats(words: list[Word], longest: int = 12,
                 shortest: int = 3) -> list[Word]:
    """Throw away a phrase immediately repeated word for word.

    The other half of the same failure. Checked longest-first so the whole loop
    goes rather than its tail, and only back-to-back -- a chorus repeating
    later in the song is a chorus, and legitimate.
    """
    out = [w.word.strip().strip(".,!?;:\u0964\u2014-").lower() for w in words]
    i = 0
    keep = [True] * len(words)
    while i < len(words):
        cut = 0
        for size in range(min(longest, (len(words) - i) // 2), shortest - 1, -1):
            if out[i:i + size] == out[i + size:i + 2 * size]:
                cut = size
                break
        if cut:
            for k in range(i + cut, i + 2 * cut):
                keep[k] = False
            i += 2 * cut
        else:
            i += 1
    return [w for w, k in zip(words, keep) if k]


def words_to_cues(words: list[Word], spans: list[tuple[float, float]],
                  gap_break: float = 0.9) -> CueTable:
    """Assign line numbers. Whisper's segments track sung phrases, so prefer them;
    fall back to splitting on inter-word gaps when segments are absent."""
    words = drop_repeats(drop_collapsed(words))
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


def voiced_gaps(vocals, starts, fps_mask=None, pad: float = 1.0,
                join: float = 2.5, least: float = 1.5,
                most: float = 25.0, hold: float = 4.0
                ) -> list[tuple[float, float]]:
    """Stretches where the stem is singing and the cue table has nothing.

    `analysis.voiced_frames` already answers "is someone singing at this
    moment" at 50fps, and `missed_windows` already turns that into a warning --
    which is all anything did with it. This turns it into the windows to go
    back and ask about, which is the only thing that recovers a region Whisper
    dropped whole: one song had no cues at all in its first 28 seconds or its
    last 18, of 162.

    Taken from the frame mask rather than from `missed_windows`, whose triples
    are cue-to-cue and cannot say WHERE inside a long gap the singing sits.
    """
    from . import analysis

    voiced, fps = fps_mask if fps_mask is not None else analysis.voiced_frames(vocals)
    if not len(voiced):
        return []
    # A cued word covers the stem until the NEXT cued word, not a fixed half
    # second. Treating it as a moment leaves an uncovered sliver between every
    # pair of cues, and merging those slivers proposes re-transcribing the
    # whole song -- measured, 80 of 91 seconds.
    covered = np.zeros(len(voiced), dtype=bool)
    heard = sorted(starts)
    for k, t in enumerate(heard):
        nxt = heard[k + 1] if k + 1 < len(heard) else t + hold
        lo = max(0, int((t - 0.2) * fps))
        covered[lo:int(min(nxt, t + hold) * fps)] = True

    out, run = [], None
    for i, sung in enumerate(voiced & ~covered):
        if sung:
            run = [i, i] if run is None else [run[0], i]
        elif run is not None:
            out.append(run)
            run = None
    if run is not None:
        out.append(run)

    # Padded, then merged. Padding alone leaves windows overlapping each
    # other, and a run of them a second apart is one hole with breaths in it --
    # asking about each separately is more uploads for less context, and
    # context is most of what the decoder has to work with.
    merged: list[list[float]] = []
    for a, b in out:
        lo, hi = max(0.0, a / fps - pad), b / fps + pad
        if merged and lo <= merged[-1][1] + join:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])

    spans = []
    for lo, hi in merged:
        if hi - lo < least:
            continue
        # Long holes go back in pieces: the point of asking again is to give
        # the decoder less to lose track of, not the same problem twice.
        while hi - lo > most:
            spans.append((round(lo, 2), round(lo + most, 2)))
            lo += most - pad
        spans.append((round(lo, 2), round(hi, 2)))
    return spans


def fill_gaps(audio, words: list[Word], key: str | None = None,
              model: str = DEFAULT_MODEL, language: str | None = None,
              prompt: str | None = None, progress=None) -> list[Word]:
    """Ask again about the stretches that are sung and have no words.

    One upload of the whole track is one chance for the decoder to lose the
    thread, and when it does it loses a region rather than a word: one song
    came back with nothing at all in its first 28 seconds of 162. Cutting that
    window out and asking about it alone recovered words the whole-file pass
    had found none of.

    Only the holes, so this is one or two short uploads rather than a second
    full pass -- measured across three songs, 1, 1 and 2 windows totalling 12
    to 26 seconds.
    """
    say = progress or (lambda m: None)
    spans = voiced_gaps(audio, [w.start for w in words])
    if not spans:
        return words

    say(f"{len(spans)} stretch(es) sung with no words; asking again")
    got = list(words)
    for lo, hi in spans:
        try:
            more, _ = transcribe_words(audio, key=key, model=model,
                                       language=language, prompt=prompt,
                                       window=(lo, hi))
        except TranscribeError as e:
            say(f"  {lo:.0f}-{hi:.0f}s: {e}")
            continue
        # Only what lands inside the hole. A window carries context either
        # side and the decoder will happily re-report words already cued.
        fresh = [w for w in more if lo <= w.start <= hi]
        say(f"  {lo:.0f}-{hi:.0f}s: {len(fresh)} more")
        got += fresh
    got.sort(key=lambda w: w.start)
    return drop_repeats(drop_collapsed(got))


def transcribe_to_cues(audio: str | Path, key: str | None = None,
                       model: str = DEFAULT_MODEL, language: str | None = None,
                       prompt: str | None = None,
                       known: str | None = None,
                       second_pass: bool = True,
                       progress=None) -> CueTable:
    """Words and timings for a vocal stem.

    With `known` -- the lyrics as the user typed them -- the transcription is
    used only for its CLOCK and the text comes from them. Measured across three
    songs, Whisper's cues land within 0.07s of actual singing while inventing
    whole phrases, so that split plays to what it is good at. Without `known`
    the transcription is all there is.
    """
    say = progress or (lambda m: None)
    words, spans = transcribe_words(audio, key=key, model=model,
                                    language=language, prompt=prompt)
    words = drop_repeats(drop_collapsed(words))
    if second_pass:
        words = fill_gaps(audio, words, key=key, model=model,
                          language=language, prompt=prompt, progress=say)
    if known and known.strip():
        return align_to_known(words, known)
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
