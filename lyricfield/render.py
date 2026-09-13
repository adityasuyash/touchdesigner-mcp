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


def park(client: TDClient) -> None:
    """Pause at frame 1 with field state cleared, ready to record."""
    client.run(
        "def main():\n"
        "    me.time.play = 0\n"
        "    op('/local/time').frame = 1\n"
        f"    sc = op({SCRIPT_TOP!r})\n"
        "    if sc is not None:\n"
        "        sc.bypass = False\n"
        f"    o = op({OUT_TOP!r})\n"
        "    if o is not None:\n"
        "        o.cook(force=True)\n"
        "    return 'parked at frame %d' % op('/local/time').frame\n"
        "print(main())"
    )
    reset_field_state(client)


def resume_playback(client: TDClient) -> None:
    client.run("me.time.play = 1\nprint('playing at frame %d' % op('/local/time').frame)")


def wait_for_container(path: Path, timeout: float = 900.0,
                       settle: float = 5.0, poll: float = 4.0) -> bool:
    """Stable size AND a parseable container. Size alone is not enough."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.exists():
            a = path.stat().st_size
            time.sleep(settle)
            b = path.stat().st_size if path.exists() else -1
            if a == b and b > 50_000 and _ffprobe(path) is not None:
                return True
        time.sleep(poll)
    return False


def mux_stems(video: Path, out: Path, vocals: Path, instrumental: Path,
              duration: float) -> None:
    """Replace TD's drifting audio with the real stem mix, copying the video."""
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-i", str(video), "-i", str(vocals), "-i", str(instrumental),
         "-filter_complex",
         "[1:a][2:a]amix=inputs=2:duration=shortest:normalize=0[a]",
         "-map", "0:v", "-map", "[a]", "-t", f"{duration:.3f}",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", str(out)],
        check=True,
    )


def render(client: TDClient, out_path: str | Path, duration: float,
           vocals: str | Path | None = None,
           instrumental: str | Path | None = None,
           fps: int = 30, pad: float = 2.5,
           top: str = OUT_TOP,
           progress=None) -> RenderResult:
    """Capture `duration` seconds and return a finished MP4 with stem audio."""
    out_path = Path(out_path)
    raw = out_path.with_name(out_path.stem + "_raw.mp4")
    say = progress or (lambda m: None)

    say("parking timeline")
    park(client)

    say(f"recording {duration + pad:.1f}s")
    client.call("render", output=str(raw), duration=duration + pad,
                top=top, fps=fps)
    resume_playback(client)

    say("waiting for TD to finish writing")
    if not wait_for_container(raw):
        raise TDUnavailable(
            f"{raw.name} never became a valid container. TD may still be writing; "
            "check the file before re-rendering."
        )

    if vocals and instrumental:
        say("muxing stem audio")
        mux_stems(raw, out_path, Path(vocals), Path(instrumental), duration)
        raw.unlink(missing_ok=True)
    else:
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


def region_stats(image: str | Path, x: int, y: int, w: int, h: int) -> dict:
    """YMIN/YAVG/YMAX over a crop, straight from ffmpeg signalstats."""
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(image),
         "-vf", f"crop={w}:{h}:{x}:{y},signalstats,metadata=print", "-f", "null", "-"],
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
