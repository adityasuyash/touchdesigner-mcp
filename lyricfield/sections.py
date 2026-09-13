"""Sectioned parameter blocks: a dataclass of flat dataclass sections.

`Config` and every video type's `Params` have the same shape -- a handful of
named sections, each a flat dataclass of scalars -- so loading, TOML emission,
flattening and validation plumbing live here once instead of being copied into
each type.

Sections are matched by name and unknown keys are ignored, which is what makes a
config file survive a type gaining or losing a tunable.
"""

from __future__ import annotations

from dataclasses import asdict, fields


def toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(toml_value(x) for x in v) + "]"
    raise TypeError(f"cannot serialise {type(v)}")


def section_names(cls) -> tuple[str, ...]:
    return tuple(f.name for f in fields(cls))


def build_sections(cls, data: dict):
    """Instantiate `cls` from a parsed TOML dict, section by section.

    Every section falls back to its defaults, and keys the section does not
    declare are skipped -- so an old config file still loads after a tunable is
    renamed, rather than raising.
    """
    kw = {}
    for f in fields(cls):
        section = f.default_factory()          # type: ignore[misc]
        for k, v in (data.get(f.name) or {}).items():
            if hasattr(section, k):
                setattr(section, k, v)
        kw[f.name] = section
    return cls(**kw)


def sections_toml(obj, header: list[str] | None = None) -> str:
    out: list[str] = list(header or [])
    if out:
        out.append("")
    for f in fields(obj):
        out.append(f"[{f.name}]")
        for k, v in asdict(getattr(obj, f.name)).items():
            out.append(f"{k} = {toml_value(v)}")
        out.append("")
    return "\n".join(out)


def flatten(obj) -> dict:
    """All sections merged into one flat dict, for injection into TouchDesigner.

    Section names are dropped, so two sections must not share a key.
    """
    p: dict = {}
    for f in fields(obj):
        p.update(asdict(getattr(obj, f.name)))
    return p
