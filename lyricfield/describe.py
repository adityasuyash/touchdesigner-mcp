"""Turn a description of a look into settings, using the local `claude` CLI.

"slower, colder, fewer flashes on the beat" is how people describe a video. The
53 tunables are how the renderer is spelled. This bridges the two, and it is the
only part of the system that asks a model anything.

It runs the `claude` binary already on this machine, so it uses the subscription
that is already paid for -- no API key, no second account, nothing to configure.

**It asks for control positions, not raw parameters.** The six named controls in
a type's `params.py` are a small, bounded, well-described vocabulary: six numbers
from 0 to 1 with a sentence each saying what they do. Raw tunables are 53
numbers with meanings that live in this repo's history, and a model asked for
those will confidently return `twinkle_frac_lo: 0.4` with no idea that the value
is nonsense. A proposal can still name specific parameters when it needs to, but
every one is clamped to its declared range and the whole result is reconciled and
validated before anyone sees it.

Nothing is applied on the strength of the model's say-so: `propose()` returns the
change, the caller previews it, and only an approved preview is saved.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


class DescribeError(RuntimeError):
    pass


DEFAULT_TIMEOUT = 180.0

# No tools. This is a text-in, JSON-out question about numbers; it has no
# business reading files or running anything, and saying so keeps it quick.
# `--max-turns 1` is deliberately absent: a single plain answer still trips it,
# and the run exits 1 with "Reached max turns" instead of returning the reply.
CLI_FLAGS = [
    "--print",
    "--output-format", "text",
    "--allowed-tools", "",
    "--append-system-prompt",
    "You answer with a single JSON object and nothing else. No prose, no code "
    "fences, no tool use. You are not editing a codebase; you are returning "
    "numbers.",
]


@dataclass
class Proposal:
    text: str = ""                        # what was asked for
    why: str = ""                         # the model's one-line reasoning
    controls: dict = field(default_factory=dict)   # key -> 0..1
    params: dict = field(default_factory=dict)     # "section.field" -> value
    changed: dict = field(default_factory=dict)    # what actually moved
    problems: list = field(default_factory=list)   # validate() on the result
    ignored: list = field(default_factory=list)    # what was refused, and why

    def to_dict(self) -> dict:
        return {"text": self.text, "why": self.why, "controls": self.controls,
                "params": self.params, "changed": self.changed,
                "problems": self.problems, "ignored": self.ignored}


def available() -> bool:
    return shutil.which("claude") is not None


def _prompt(cfg, text: str) -> str:
    vt = cfg.video_type
    controls = vt.controls(cfg.params)
    ranges = vt.ranges()

    lines = [
        f"You are tuning a music-video renderer called {vt.name!r}: {vt.description}.",
        "",
        "Someone described how they want it to look. Translate that description "
        "into settings. Answer with JSON and nothing else.",
        "",
        f"THE DESCRIPTION: {text.strip()}",
        "",
        "THE CONTROLS. Each is a number from 0 to 1. Current positions:",
    ]
    for c in controls:
        lines.append(f"  {c['key']:10s} = {c['value']:.2f}   {c['label']}: {c['hint']}")
    lines += [
        "",
        "Prefer these. They are the whole vocabulary for ordinary changes, and "
        "each one moves several underlying settings together and coherently.",
        "",
        "If, and only if, the description asks for something no control covers, "
        "you may also name individual settings. Valid names and their "
        "(min, max) bounds:",
    ]
    for k, (lo, hi, _step) in sorted(ranges.items()):
        lines.append(f"  {k}: ({lo}, {hi})")
    lines += [
        "",
        "Answer in exactly this shape:",
        '{"controls": {"motion": 0.2}, "params": {}, '
        '"why": "one short sentence"}',
        "",
        "Rules:",
        "- Only move what the description actually asks for. Leave the rest out; "
        "an omitted control keeps its current position.",
        "- Control values are 0 to 1. Parameter values must sit inside the "
        "bounds listed above.",
        "- Parameter keys are bare names as listed, not section-prefixed.",
        "- No commentary, no code fences, no explanation outside the JSON.",
    ]
    return "\n".join(lines)


def _extract_json(raw: str) -> dict:
    """The reply should be bare JSON. Be forgiving about fences anyway."""
    s = raw.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", s, re.S)
    if fence:
        s = fence.group(1).strip()
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        raise DescribeError(f"no JSON in the reply: {raw[:200]!r}")
    try:
        out = json.loads(s[start:end + 1])
    except json.JSONDecodeError as e:
        raise DescribeError(f"reply was not valid JSON: {e}") from e
    if not isinstance(out, dict):
        raise DescribeError("reply was JSON, but not an object")
    return out


def ask(prompt: str, timeout: float = DEFAULT_TIMEOUT, cwd: Path | None = None) -> str:
    if not available():
        raise DescribeError(
            "the `claude` command is not on PATH. This feature uses the Claude "
            "Code CLI that is already installed and signed in on this machine.")
    # Run it somewhere empty. Started inside this repo it reads the project's
    # CLAUDE.md, decides it is here to work on the codebase, and answers with an
    # account of which shell commands it was not allowed to run -- instead of
    # the four numbers it was asked for.
    with tempfile.TemporaryDirectory(prefix="lyricfield_ask_") as scratch:
        try:
            proc = subprocess.run(
                ["claude", *CLI_FLAGS, prompt],
                capture_output=True, text=True, timeout=timeout,
                cwd=str(cwd) if cwd else scratch,
            )
        except subprocess.TimeoutExpired as e:
            raise DescribeError(
                f"claude did not answer within {timeout:.0f}s") from e
    if proc.returncode != 0:
        raise DescribeError(
            f"claude exited {proc.returncode}: "
            f"{(proc.stderr or proc.stdout or '').strip()[:300]}")
    if not proc.stdout.strip():
        raise DescribeError("claude returned nothing")
    return proc.stdout


def propose(cfg, text: str, timeout: float = DEFAULT_TIMEOUT) -> Proposal:
    """Ask for settings matching `text`, apply them to `cfg`, and report.

    `cfg` is mutated, because the caller's next move is to push it and render a
    preview. Nothing is saved here -- that is the approval step's job.
    """
    if not (text or "").strip():
        raise DescribeError("no description given")

    vt = cfg.video_type
    reply = _extract_json(ask(_prompt(cfg, text), timeout=timeout))

    out = Proposal(text=text.strip(), why=str(reply.get("why", "")).strip())
    before = _snapshot(cfg)

    valid = {c["key"] for c in vt.controls(cfg.params)}
    for key, value in (reply.get("controls") or {}).items():
        if key not in valid:
            out.ignored.append(f"{key}: not a control of this video type")
            continue
        try:
            vt.apply_control(cfg.params, key, float(value))
            out.controls[key] = round(min(1.0, max(0.0, float(value))), 4)
        except (TypeError, ValueError):
            out.ignored.append(f"{key}: {value!r} is not a number")

    ranges = vt.ranges()
    for key, value in (reply.get("params") or {}).items():
        name = key.split(".")[-1]
        if name not in ranges:
            out.ignored.append(f"{key}: not a setting of this video type")
            continue
        try:
            v = float(value)
        except (TypeError, ValueError):
            out.ignored.append(f"{key}: {value!r} is not a number")
            continue
        lo, hi, _ = ranges[name]
        if not (lo <= v <= hi):
            out.ignored.append(f"{key}: {v} is outside ({lo}, {hi}); clamped")
            v = min(hi, max(lo, v))
        if not _assign(cfg.params, name, v):
            out.ignored.append(f"{key}: no section of this type has it")
            continue
        out.params[name] = v

    _reconcile(cfg.params)
    out.changed = _diff(before, _snapshot(cfg))
    out.problems = cfg.validate()
    if not out.changed and not out.ignored:
        out.ignored.append("nothing in the description mapped to a setting")
    return out


# ---------------------------------------------------------------- internals

def _sections(params) -> list[str]:
    from .sections import section_names
    return list(section_names(type(params)))


def _snapshot(cfg) -> dict:
    out = {}
    for name in _sections(cfg.params):
        sec = getattr(cfg.params, name, None)
        for k, v in vars(sec or object()).items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                out[f"{name}.{k}"] = v
    return out


def _assign(params, name: str, value: float) -> bool:
    for section in _sections(params):
        sec = getattr(params, section, None)
        if sec is not None and hasattr(sec, name):
            setattr(sec, name, value)
            return True
    return False


def _reconcile(params) -> None:
    import importlib
    mod = importlib.import_module(type(params).__module__)
    fn = getattr(mod, "reconcile", None)
    if fn:
        fn(params)


def _diff(before: dict, after: dict) -> dict:
    return {k: [before[k], after[k]] for k in after
            if k in before and abs(after[k] - before[k]) > 1e-9}
