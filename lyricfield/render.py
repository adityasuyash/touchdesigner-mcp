"""Render orchestration.

Three things here are not optional, each learned the hard way:

  * START ALIGNMENT. The timeline free-runs while commands are in flight, and a
    round trip to TD can take seconds, so setting frame 1 and then calling render
    lands somewhere else entirely. Park the timeline PAUSED at frame 1, start the
    recording, and only then resume -- that gives zero drift.

  * CONTAINER VALIDATION. TD reports the MP4 as finished while it is still
    writing the moov atom. A render that looked complete failed remuxing with
    "moov atom not found", and by then the PNG frames had been deleted. Wait for
    the size to stabilise AND for ffprobe to parse it.

  * AUDIO. TD's AudioFileOut records in wall-clock time, and cooking runs slower
    than real time, so its WAV ends up longer than the picture and drifts. Always
    discard it and mux the original stems with ffmpeg instead.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .sync import OUT_TOP, SCRIPT_TOP, reset_field_state
from .td_client import TDClient, TDUnavailable


@dataclass
class RenderResult:
    path: Path
    duration: float
    width: int
    height: int
    fps: int


def _ffprobe(path: Path) -> dict | None:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height,r_frame_rate",
         "-of", "json", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        return None
    import json
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return None


def _reporter(progress):
    """Wrap a progress callback so it may be called with a fraction.

    Most callers pass a plain `say(message)`. The render wants to report how far
    along it is as well, and rather than change every caller, this forwards two
    arguments where the callback accepts them and one where it does not.
    """
    if progress is None:
        return lambda m, frac=None: None

    def say(m, frac=None):
        try:
            progress(m, frac)
        except TypeError:
            progress(m)
    return say


class SeekFailed(RuntimeError):
    """The timeline did not go where it was told."""


def park(client: TDClient, at_seconds: float = 0.0,
         covers: float = 0.0) -> float:
    """Pause at `at_seconds` with field state cleared, ready to record.

    Returns the second the timeline actually sits on.

    **This used to be able to fail in total silence, and did.** TouchDesigner
    confines the playhead to the play range (`rangestart`..`rangeend`), and a
    frame assignment outside it is discarded with no error and no exception --
    `me.time.frame += 100` moves, `me.time.frame = <past rangeend>` does nothing
    at all. Every new project inherits `rangeend` from the project it was forked
    from, which traced back to a 90-second benchmark track, so on a 264s song
    every seek past 1:30 was thrown away. The timeline then simply looped where
    it was, and the render recorded an unrelated part of the song under correct
    audio -- the picture at 0:16 while the vocal sang 3:08.

    So: widen the range to cover what is about to be recorded, seek, then read
    the frame back and refuse to continue if it is not where it was sent.
    """
    from . import sync

    # Grow only to what the caller says it is about to record. Deliberately not
    # `max(at_seconds, covers)`: sizing the timeline to fit whatever start it was
    # handed means a nonsense start silently stretches the project to fit rather
    # than being caught below, which is the failure mode this whole function
    # exists to stop.
    rate = 60.0
    if covers > 0:
        info = sync.set_timeline_length(client, float(covers) + 2.0)
        rate = float(info.get("rate") or rate) if isinstance(info, dict) else rate
    else:
        out = client.run("print(op('/local/time').rate)").strip()
        try:
            rate = float(out)
        except ValueError:
            pass

    want = max(1, int(round(float(at_seconds) * rate)))
    out = client.run(
        "def main():\n"
        "    me.time.play = 0\n"
        f"    op('/local/time').frame = {want}\n"
        f"    sc = op({SCRIPT_TOP!r})\n"
        "    if sc is not None:\n"
        "        sc.bypass = False\n"
        f"    o = op({OUT_TOP!r})\n"
        "    if o is not None:\n"
        "        o.cook(force=True)\n"
        "    t = op('/local/time')\n"
        "    return '%d %d %d' % (t.frame, t.par.rangeend.eval(), t.end)\n"
        "print(main())"
    ).strip()
    try:
        landed, range_end, end = (int(float(v)) for v in out.split())
    except ValueError as e:
        raise SeekFailed(f"could not read the timeline back: {out!r}") from e

    # One frame of slack: the playhead can settle on a neighbour, but it cannot
    # be somewhere else entirely.
    if abs(landed - want) > 1:
        raise SeekFailed(
            f"asked the timeline for frame {want} ({at_seconds:.1f}s) and it "
            f"sits on {landed} ({landed / rate:.1f}s). The play range is "
            f"1..{range_end} of {end} frames — a seek outside it is discarded "
            f"silently, and anything recorded now would be the wrong part of "
            f"the song."
        )
    reset_field_state(client)
    return landed / rate


def recorder_present(client: TDClient) -> bool:
    """Is a Movie File Out still sitting in the network from an earlier render?

    Its presence is what makes the *next* render refuse to start, so one
    aborted preview silently breaks every render after it.
    """
    try:
        out = client.run(
            "def main():\n"
            "    return repr(op('/project1/_mcp_movieout') is not None)\n"
            "print(main())"
        ).strip()
    except Exception:
        return False
    return out == "True"


def stop_recording(client: TDClient) -> str:
    """Tear down a recording that is still in the network, whatever its state.

    A stopped run leaves the Movie File Out behind: `render` schedules its own
    finalize in timeline frames, so halting playback strands the recorder, and
    the *next* render then refuses to start -- one aborted preview quietly
    breaks every render after it until someone notices the operator sitting
    there. Stopping is the supported route; destroying it is the fallback for
    when TD says there is no active recording but the operator is still there.
    """
    try:
        client.call("render", output="", duration=0, action="stop")
        return "stopped"
    except Exception:
        pass
    try:
        client.run(
            "def main():\n"
            "    o = op('/project1/_mcp_movieout')\n"
            "    if o is None:\n"
            "        return 'nothing to clear'\n"
            "    o.destroy()\n"
            "    return 'cleared'\n"
            "print(main())"
        )
        return "cleared"
    except Exception as e:
        return f"could not clear the recorder: {e}"


def resume_playback(client: TDClient) -> None:
    client.run("me.time.play = 1\nprint('playing at frame %d' % op('/local/time').frame)")


def recording_progress(client: TDClient) -> dict:
    """How far the recording in flight has got, in frames written.

    Frames, not seconds: TouchDesigner cooks slower than real time by a factor
    that varies with the network, so elapsed time says nothing about how much is
    done. One PNG lands per captured frame, and the server counts them.
    """
    try:
        out = client.call("render", action="status")
    except Exception:
        return {}
    if isinstance(out, dict):
        return out
    # The tool answers with a JSON document as text rather than a mapping.
    try:
        import json
        parsed = json.loads(str(out))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def wait_for_container(path: Path, timeout: float = 900.0,
                       settle: float = 5.0, poll: float = 4.0,
                       should_stop=None, client: TDClient | None = None,
                       progress=None) -> bool:
    """Stable size AND a parseable container. Size alone is not enough.

    Reports progress while it waits, when given a client to ask. This is the
    multi-minute step of the whole run, and without it the UI sat on one frozen
    message with a progress bar that could not move.
    """
    say = _reporter(progress)
    deadline = time.time() + timeout
    last_said = 0.0
    while time.time() < deadline:
        if should_stop is not None and should_stop():
            return False
        if path.exists():
            a = path.stat().st_size
            time.sleep(settle)
            b = path.stat().st_size if path.exists() else -1
            if a == b and b > 50_000 and _ffprobe(path) is not None:
                return True
        elif client is not None and time.time() - last_said > 3.0:
            last_said = time.time()
            st = recording_progress(client)
            if st.get("recording") and st.get("expected"):
                say(f"recording {st['frames']} of {st['expected']} frames",
                    st.get("fraction"))
        time.sleep(poll)
    return False


def mux_audio(video: Path, out: Path, source: Path,
              duration: float, start: float = 0.0) -> None:
    """Attach one audio file to the picture, seeked to the same moment.

    For a video type that needs no stem separation there is nothing to mix --
    the song's own mix is the audio. Without this branch such a type shipped a
    **silent** MP4, because the only muxer required both a vocal and an
    instrumental and quietly fell through to copying the picture alone.
    """
    seek = ["-ss", f"{start:.3f}"] if start else []
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(video), *seek, "-i", str(source),
         "-map", "0:v:0", "-map", "1:a:0",
         "-t", f"{duration:.3f}",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-movflags", "+faststart", "-shortest", str(out)],
        check=True,
    )


def mux_stems(video: Path, out: Path, vocals: Path, instrumental: Path,
              duration: float, start: float = 0.0) -> None:
    """Replace TD's drifting audio with the real stem mix, copying the video.

    `start` seeks both stems, so a preview taken from the middle of a song is
    heard from the middle too rather than against the opening bars.
    """
    seek = ["-ss", f"{start:.3f}"] if start else []
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(video), *seek, "-i", str(vocals), *seek, "-i", str(instrumental),
         "-filter_complex",
         "[1:a][2:a]amix=inputs=2:duration=shortest:normalize=0[a]",
         "-map", "0:v", "-map", "[a]", "-t", f"{duration:.3f}",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(out)],
        check=True,
    )


def render(client: TDClient, out_path: str | Path, duration: float,
           vocals: str | Path | None = None,
           instrumental: str | Path | None = None,
           source: str | Path | None = None,
           fps: int = 30, pad: float = 2.5,
           top: str = OUT_TOP,
           should_stop=None, start: float = 0.0,
           progress=None) -> RenderResult:
    """Capture `duration` seconds and return a finished MP4 with stem audio."""
    out_path = Path(out_path)
    raw = out_path.with_name(out_path.stem + "_raw.mp4")
    say = _reporter(progress)

    # `covers` so the timeline and its play range are wide enough for the whole
    # recording, not just its first frame -- a render that runs off the end of
    # the range loops back to the start mid-take.
    say(f"parking at {start:.1f}s" if start else "parking timeline")
    park(client, start, covers=start + duration + pad)

    say(f"recording {duration + pad:.1f}s")
    client.call("render", output=str(raw), duration=duration + pad,
                top=top, fps=fps)
    resume_playback(client)

    # TouchDesigner cooks slower than real time, so the wait has to scale with
    # the recording. A fixed 900s budget meant any full-length render of a track
    # over about six minutes was abandoned and renamed .failed.mp4 while it was
    # still being written.
    patience = max(900.0, (duration + pad) * 6.0 + 120.0)
    say(f"recording {duration + pad:.0f}s (up to {patience / 60:.0f} min)")
    if not wait_for_container(raw, timeout=patience, should_stop=should_stop,
                              client=client, progress=say):
        # The automatic finalize is scheduled in timeline frames, so anything
        # that pauses playback leaves the recording stranded: operators in the
        # network, frames on disk, and the next render refusing to start.
        # Finalize explicitly, then keep the partial under a name that says so.
        say("render did not complete; finalizing the stranded recording")
        try:
            client.call("render", output=str(raw), duration=duration,
                        action="stop")
        except Exception:
            pass
        if raw.exists():
            failed = out_path.with_name(out_path.stem + ".failed.mp4")
            raw.replace(failed)
            say(f"partial output kept at {failed.name}")
        raise TDUnavailable(
            f"{raw.name} never became a valid container. The recording has been "
            "stopped and any partial output renamed; re-render when ready."
        )

    # TouchDesigner's own recorded audio drifts, so it is always discarded and
    # the real audio attached here. Which audio depends on what this video type
    # asked ingest for: a type that needs no separation has no stems, and used
    # to end up with a silent file.
    if vocals and instrumental:
        say("muxing stem audio")
        mux_stems(raw, out_path, Path(vocals), Path(instrumental), duration, start)
        raw.unlink(missing_ok=True)
    elif source:
        say("muxing the source mix")
        mux_audio(raw, out_path, Path(source), duration, start)
        raw.unlink(missing_ok=True)
    else:
        say("no audio to attach; the file will be silent")
        raw.replace(out_path)

    info = _ffprobe(out_path) or {}
    vs = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    num, _, den = (vs.get("r_frame_rate") or "30/1").partition("/")
    say("done")
    return RenderResult(
        path=out_path,
        duration=float(info.get("format", {}).get("duration", 0.0)),
        width=int(vs.get("width", 0)),
        height=int(vs.get("height", 0)),
        fps=int(round(float(num) / float(den or 1))),
    )


def sample_frames(video: str | Path, times: list[float],
                  out_dir: str | Path) -> list[Path]:
    """Pull stills out of a finished MP4. Verifying in TD is not enough -- content
    that measured fine upstream has been crushed to black by the encode before."""
    video, out_dir = Path(video), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for t in times:
        dst = out_dir / f"{video.stem}_{t:g}s.png"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-ss", f"{t:g}", "-i", str(video), "-frames:v", "1", str(dst)],
            check=True,
        )
        made.append(dst)
    return made


def measure_output(video: str | Path, cue_times, start: float,
                   fps: float = 10.0, lit: int = 200, ink: int = 8,
                   plateau: tuple[float, float] = (0.12, 0.92)) -> dict:
    """Measure a finished render against the song it is supposed to be.

    This exists because a 30-second render of *entirely the wrong part of the
    song* was written to disk marked "verified with no problems". Everything
    the verifier looked at -- brightness per region, letters staying inside the
    band -- was fine. Nobody checked whether the picture had anything to do with
    the audio playing over it.

    Three things are measured in one decode:

      * **does the picture follow the words** -- bright pixels during a cued
        word's plateau against bright pixels between words. When the picture is
        the song, light only happens on cue. The failing render measured *more*
        light between words than during them.
      * **is the frame filled** -- how much of the frame's height has anything
        drawn in it. This is what catches geometry drift: a lost text
        calibration dropped the row pitch from 53px to 40px, so the grid drew
        short and the bottom third of every frame was empty, and nothing
        noticed.
      * **black frames** -- how many, and the longest unbroken run.

    Frames are streamed and reduced one at a time. Buffering the decode held
    2.4GB for a four-minute track and 5.5GB for ten minutes, so the check that
    was meant to make long renders trustworthy could not be run on them.
    """
    import numpy as np

    info = _ffprobe(Path(video)) or {}
    vs = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
    w, h = int(vs.get("width", 0)), int(vs.get("height", 0))
    times = sorted(float(t) for t in cue_times)
    if not (w and h):
        return {"checked": False, "why": "no video stream"}

    frame_bytes = w * h
    proc = subprocess.Popen(
        ["ffmpeg", "-v", "error", "-i", str(video), "-vf", f"fps={fps:g}",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    bright: list[int] = []
    dark: list[bool] = []
    rows_seen = np.zeros(h, dtype=bool)
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if not buf or len(buf) < frame_bytes:
                break
            f = np.frombuffer(buf, dtype=np.uint8).reshape(h, w)
            bright.append(int((f > lit).sum()))
            dark.append(bool(f.max() < 2))
            rows_seen |= (f > ink).any(axis=1)
    finally:
        if proc.stdout:
            proc.stdout.close()
        proc.wait()

    n = len(bright)
    if n < 4:
        return {"checked": False, "why": "too few frames to measure"}

    out = {
        "checked": True,
        "frames": n,
        "seconds": round(n / fps, 2),
        "black_fraction": round(float(np.mean(dark)), 4),
        "longest_black_seconds": round(_longest_run(dark) / fps, 2),
    }

    # How much of the frame's height ever has anything in it.
    used = np.flatnonzero(rows_seen)
    out["frame_fill"] = round(float(used[-1] - used[0]) / h, 3) if len(used) > 1 else 0.0

    if times:
        b = np.array(bright, float)
        t = float(start) + np.arange(n) / fps
        # When a word is at full brightness, taken from the configuration rather
        # than assumed. Hardcoding it meant that lengthening `hold` moved real
        # lit frames *outside* the window the check was looking in, and the
        # check then reported that the picture did not follow the words -- of a
        # render that was perfectly correct.
        lo, hi = float(plateau[0]), float(plateau[1])
        inside = np.zeros(n, bool)
        for c in times:
            inside |= (t >= c + lo) & (t <= c + hi)
        ins = float(b[inside].mean()) if inside.any() else 0.0
        outside = float(b[~inside].mean()) if (~inside).any() else 0.0
        out.update({
            "bright_in_cue": round(ins, 1),
            "bright_outside": round(outside, 1),
            "outside_frames": int((~inside).sum()),
            # A song can be dense enough that nearly every frame is inside a
            # cue, and then "outside" is a handful of frames whose mean says
            # little. Reported either way; the caller decides.
            "ratio": round(ins / outside, 2) if outside > 1.0 else None,
        })

        # When there is nothing outside to compare against -- a densely sung
        # song, especially with long holds -- the ratio abstains, and a check
        # that abstains catches nothing. How *many* words are lit still varies
        # frame to frame, so correlate brightness against that instead. A
        # picture that belongs to this song tracks it; one from elsewhere does
        # not, and neither does one that is not lighting words at all.
        active = np.zeros(n, float)
        for c in times:
            active += ((t >= c + lo) & (t <= c + hi)).astype(float)
        if active.std() > 1e-9 and b.std() > 1e-9:
            out["follows_words"] = round(float(np.corrcoef(active, b)[0, 1]), 3)
        else:
            out["follows_words"] = None
    return out


# The name this was introduced as. Kept so nothing that already calls it breaks.
picture_matches_cues = measure_output


def _longest_run(mask) -> int:
    best = run = 0
    for v in mask:
        run = run + 1 if v else 0
        best = max(best, run)
    return best


def region_stats(image: str | Path, x: int | None = None, y: int | None = None,
                 w: int | None = None, h: int | None = None) -> dict:
    """YMIN/YAVG/YMAX over a crop, straight from ffmpeg signalstats.

    With no crop given, measures the whole frame -- which is what a video type
    that declares no regions of interest gets.
    """
    crop = "" if None in (x, y, w, h) else f"crop={w}:{h}:{x}:{y},"
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(image),
         "-vf", f"{crop}signalstats,metadata=print", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    stats: dict = {}
    for line in out.stderr.splitlines():
        if "signalstats." in line:
            key, _, val = line.split("signalstats.")[-1].partition("=")
            try:
                stats[key.strip()] = float(val)
            except ValueError:
                pass
    return stats
