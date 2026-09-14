"""Named controls: the few knobs a person is offered, over the many a type has.

A renderer declares raw tunables because the field script needs them. A wall of
internal variable names is not a set of choices, so a type that means to be used
by a person also declares `CONTROLS` -- each one a named idea ("Brightness",
"Beat") that moves several tunables together along measured spans.

The *machinery* for that is identical for every renderer, and it was copied into
every type. Normalising whitespace and hashing the bodies, `pulse_grid` and
`swell` had byte-identical `apply_control` and `control_values`, with
`lyric_grid`'s a near-copy -- ninety lines, three times over, and nine times
over once there are nine renderers. Only `CONTROLS` and `reconcile` differ per
type, so those stay with the type and everything else lives here.

A type wires itself up with:

    from .._controls import Control, bind_controls
    CONTROLS = (Control(...), ...)
    control_values, apply_control, controls_payload = bind_controls(
        CONTROLS, reconcile)
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Control:
    """One named choice, and the tunables it moves.

    `lead` is the tunable the control's own position is read back from, so the
    UI can show where a slider sits after a config is loaded. It must be one of
    `targets`, which a meta-test enforces -- a lead that is not a target reads
    back a number the control cannot set.
    """

    key: str
    label: str
    hint: str
    lead: str
    targets: dict[str, tuple[float, float]]


def get_path(params, path: str) -> float:
    """Read `section.field` off a params object."""
    section, name = path.split(".")
    return float(getattr(getattr(params, section), name))


def set_path(params, path: str, value: float) -> None:
    section, name = path.split(".")
    setattr(getattr(params, section), name, value)


def bind_controls(controls, reconcile):
    """The three functions a type exposes, bound to its own controls.

    `reconcile` is the type's own: settling the relationships `validate()`
    insists on is the one part of this that cannot be shared, because it is
    about that renderer's tunables and no other's.
    """

    def control_values(params) -> dict[str, float]:
        out = {}
        for c in controls:
            lo, hi = c.targets[c.lead]
            v = (get_path(params, c.lead) - lo) / (hi - lo) if hi != lo else 0.0
            out[c.key] = round(min(1.0, max(0.0, v)), 4)
        return out

    def apply_control(params, key: str, value: float) -> dict:
        control = next((c for c in controls if c.key == key), None)
        if control is None:
            raise KeyError(f"no such control: {key}")
        v = min(1.0, max(0.0, float(value)))
        for path, (lo, hi) in control.targets.items():
            set_path(params, path, round(lo + (hi - lo) * v, 4))
        reconcile(params)
        return {p: get_path(params, p) for p in control.targets}

    def controls_payload(params) -> list[dict]:
        now = control_values(params)
        return [{"key": c.key, "label": c.label, "hint": c.hint,
                 "value": now[c.key], "drives": sorted(c.targets)}
                for c in controls]

    return control_values, apply_control, controls_payload
