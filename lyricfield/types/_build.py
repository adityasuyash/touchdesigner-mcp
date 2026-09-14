"""The builder engine: how a renderer's network is put into TouchDesigner.

Every video type declares its own graph as a list of `OpSpec` and hands it to
these functions. Nothing here knows what the graph draws -- there are no
glyphs, rows, columns or fonts in this file, and that is the point.

It lived inside `lyric_grid/build.py`, which meant a second renderer either
imported the first one's module or copied a hundred lines. Both happened: the
two beatsync types are twenty-six lines that delegate to `lyric_grid.build`,
which is why all three drew the same character grid. Borrow the engine, not
the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field

ROOT = "/project1"

# Operators the build must never touch: the MCP server it is talking through,
# and the scratch operators the render tool creates.
PROTECTED = ("td_mcp_server", "_mcp_movieout", "_mcp_audioout")


@dataclass
class OpSpec:
    name: str
    type: str                                   # TD type constant, e.g. 'blurTOP'
    pos: tuple[int, int]
    params: dict = field(default_factory=dict)  # constant values
    exprs: dict = field(default_factory=dict)   # expression strings
    inputs: list[str] = field(default_factory=list)   # sibling names, in order
    # Create only if absent, never replace. The `create` tool destroys a
    # same-named operator first, so without this a rebuild would silently wipe
    # the cue table -- the one thing in the network that may exist nowhere else.
    preserve: bool = False


def _py(v) -> str:
    return repr(v)


def _run(client, body: str, timeout: float | None = None) -> str:
    """Run a function body inside TD and return what it printed.

    Everything is wrapped in `main()` because the server's exec scope gives
    module-level names no visibility inside nested defs.
    """
    return client.run("def main():\n" + body + "\nprint(main())", timeout=timeout)


def create_ops(client, specs, progress=None, container: str = ROOT) -> list[str]:
    """Create every operator with its constant parameters, no wiring yet.

    Expressions and connections are applied afterwards, once every operator they
    reference exists -- otherwise the server evaluates a reference to a missing
    operator and reports it as a failure.
    """
    say = progress or (lambda m: None)
    problems: list[str] = []
    for s in specs:
        if s.preserve:
            made = _run(client, f"""
    parent = op({container!r})
    o = parent.op({s.name!r})
    if o is not None:
        return 'kept'
    o = parent.create({s.type}, {s.name!r})
    o.nodeX, o.nodeY = {s.pos[0]}, {s.pos[1]}
    return 'created'
""").strip()
            say(f"{s.name}: {made}")
            continue
        say(f"creating {s.name} ({s.type})")
        res = client.call("create", type=s.type, name=s.name, parent=container,
                          nodeX=s.pos[0], nodeY=s.pos[1], params=s.params)
        if '"errors"' in res:
            problems.append(f"{s.name}: {res}")
    return problems


def drop_autocreated(client, specs, progress=None, container: str = ROOT) -> list[str]:
    """Remove the callbacks DAT a Script TOP makes for itself.

    Creating a scriptTOP named `v7_script` makes a `v7_script_callbacks` DAT
    alongside it. We create that DAT ourselves first (it is preserved content,
    holding the field script), so TouchDesigner's copy lands as
    `v7_script_callbacks1` and is left orphaned in the network.
    """
    say = progress or (lambda m: None)
    # Only the Script TOP's own callbacks DAT, by exact name. An earlier version
    # matched any spec name plus digits and destroyed `v6_aa2` -- a pre-existing
    # operator that merely looked like "v6_aa" with a suffix. A builder must
    # never delete something it did not create.
    scripts = [sp.name for sp in specs if sp.type == "scriptTOP"]
    suspects = [f"{n}_callbacks{i}" for n in scripts for i in range(1, 10)]
    out = _run(client, f"""
    parent = op({container!r})
    dropped = []
    for n in {suspects!r}:
        c = parent.op(n)
        if c is not None:
            dropped.append(n)
            c.destroy()
    return repr(dropped)
""")
    try:
        dropped = eval(out.strip())
    except Exception:
        return []
    if dropped:
        say(f"removed auto-created duplicates: {dropped}")
    return dropped


def wire_ops(client, specs, progress=None, container: str = ROOT) -> list[str]:
    say = progress or (lambda m: None)
    conns = []
    for s in specs:
        for i, src in enumerate(s.inputs):
            conns.append({"from": f"{container}/{src}", "to": f"{container}/{s.name}",
                          "to_input": i})
    if not conns:
        return []
    say(f"wiring {len(conns)} connections")
    res = client.call("wire", connections=conns)
    return [res] if '"errors"' in res else []


def apply_exprs(client, specs, progress=None, container: str = ROOT) -> list[str]:
    say = progress or (lambda m: None)
    problems = []
    for s in specs:
        if not s.exprs:
            continue
        say(f"expressions on {s.name}")
        res = client.call("set", path=f"{container}/{s.name}", exprs=s.exprs)
        if '"errors"' in res:
            problems.append(f"{s.name}: {res}")
    return problems


def check_types(client, specs) -> list[str]:
    """Fail before creating anything if a type constant does not exist.

    `compositeTOP` vs `compTOP` and friends are easy to get wrong, and a failure
    halfway through leaves a half-built network.
    """
    names = sorted({s.type for s in specs})
    out = _run(client, f"""
    import td
    missing = [n for n in {names!r} if not hasattr(td, n)]
    return repr(missing)
""")
    try:
        return eval(out.strip())
    except Exception:
        return []
