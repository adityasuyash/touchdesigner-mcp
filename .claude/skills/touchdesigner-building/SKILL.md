---
name: touchdesigner-building
description: Building TouchDesigner projects via MCP tools. Use when creating operators, writing shaders, wiring networks, setting parameters, or debugging TD projects. Covers correct parameter names, GLSL workflow, feedback loops, and the iterative observe loop.
---

# Building in TouchDesigner via MCP

## The Build Loop

Every TD task follows this cycle:

1. **Orient** — `map` to see what exists and where (shows `@(x,y)` coordinates on every node)
2. **Look up** — `docs` for every operator type BEFORE creating it
3. **Build** — `create` for operators (requires `nodeX`/`nodeY` — read positions from `map` and place nearby), or `run` for complex multi-op scripts
4. **Observe** — `observe` with explicit `top` path to see the output
5. **Refine** — `edit` for shader tweaks, `set` for param changes (validates names, handles expressions)
6. Repeat 4-5 until it looks right

## Hard Rules

### Always call `docs` before creating operators

TD parameter names are abbreviated and non-obvious. Guessing causes silent failures.

**Examples of wrong guesses:**

| You'd guess | Actual name | Operator |
|---|---|---|
| `roughness` | `rough` | noiseCHOP/TOP |
| `type` (for waveform) | `wavetype` | lfoCHOP |
| `saturation` | `saturationmult` | hsvadjustTOP |
| `hue` | `hueoffset` | hsvadjustTOP |
| `mode` / `blend` | `operand` | compositeTOP |
| `brightness` | `brightness1` | levelTOP |
| `radius` / `filtersize` | `size` | blurTOP |
| `harmonics` | `harmon` | noiseCHOP/TOP |
| `multiply` | `gain` | mathCHOP |
| `rotation` | `rotate` (transformTOP) but `r` (compositeTOP) | varies |

Use `docs(type='list_types', family='TOP')` to find type constants before `root.create()`.

### Parameters: `.val` vs `.eval()` vs `.expr`

TD's Par class has three distinct access modes ([Par Class docs](https://docs.derivative.ca/Par_Class)):

- `.val` — get/set the **constant mode** value only (ignores expressions/exports)
- `.eval()` — returns the **current working value** regardless of mode (always safe to read)
- `.expr` — get/set the expression string; setting this puts the param into expression mode

```python
# Static value → assign directly (sets constant mode)
op.par.frequency = 0.5

# Dynamic/time-based → use .expr (switches to expression mode)
op.par.rotate.expr = "me.time.seconds * 1.5"

# WRONG — string to numeric par → ERROR
op.par.rotate = "me.time.seconds * 1.5"

# Reading values: .eval() is always correct
current = op('/project1/my_op').par.rotate.eval()  # works in any mode
```

**Gotcha:** `par.x` returns a parameter *object*, not a number. When passing to Python functions that need actual numbers, use `.eval()`:
```python
round(op('geo1').par.tx.eval(), 2)  # correct
round(op('geo1').par.tx, 2)         # may error in some contexts
```

### GLSL uniform wiring

Per the [GLSL TOP docs](https://docs.derivative.ca/GLSL_TOP), the "Load Uniform Names" button pre-fills uniform params from shader declarations — but the compiler strips unused uniforms, and pulsing from scripts is unreliable. Wire uniforms manually via the Vectors page:

```python
glsl.par.vec0name = 'uTime'
glsl.par.vec0valuex.expr = "me.time.seconds"
```

For multi-value uniforms from CHOPs:
```python
glsl.par.vec0name = 'uParams'
glsl.par.vec0valuex.expr = "op('my_chop')['chan1']"
glsl.par.vec0valuey.expr = "op('my_chop')['chan2']"
```

**Gotcha:** The uniform name in `vec0name` must exactly match the GLSL `uniform` declaration. GLSL types map to pages: `vec4` → Vectors, `float[N]` → Arrays, `mat4` → Matrices. Use `#extension` directives via the Preprocess Directives param (`predat`), not inline in the pixel shader — TD prepends its own declarations before your code.

### Always pass explicit `top` path to `observe`

Auto-detection only finds ops named `out`, `out1`, `render`, `comp`, `null1`. Real projects use custom names — always specify the path.

### Clean up before re-running

The `create` tool handles this automatically (destroy-before-create). But when using `run` for multi-op scripts, add cleanup to prevent duplicates (`glsl_main1`, `glsl_main2`):

```python
for name in ['my_glsl', 'my_glsl_pixel', 'my_out']:
    o = root.op(name)
    if o: o.destroy()
```

### Recording with `render`

The `render` tool captures MP4 video using TD-native recording (MovieFileOut TOP + optional AudioFileOut CHOP). Both `output` and `duration` are required.

```
render: output="my_video.mp4", duration=10, fps=30
```

**Audio capture** — pass `audio_chop` to record synchronized audio:
```
render: output="my_video.mp4", duration=10, audio_chop="/project1/audiodevicein1"
```

**Important:** TD's timeline must be playing for frames to record. The tool auto-extends the timeline to avoid looping mid-record. Requires ffmpeg for the final PNG-sequence-to-MP4 encode.

### Resolution management

TOPs inherit resolution from their first input. Problems happen when a TOP has no input or its input hasn't resolved yet:

- **feedbackTOP** defaults to 128x128 when created without an input — always set `outputresolution='custom'`, `resmult=False`, and explicit `resolutionw/h` on it
- **Chain roots** (any TOP with no input: noiseTOP, constantTOP, glslTOP, renderTOP) should have explicit resolution set
- **Mid-chain TOPs** generally inherit correctly if wired after the source has its resolution set
- If resolution is wrong after setting params, destroy and recreate the operator

### 3D instancing basics

Instance params live on `geometryCOMP`, not `renderTOP`:

- Use `docs(type='geometryCOMP', filter='instance')` to look up Instance page params
- Instance data comes from a CHOP with channels named `tx`, `ty`, `tz`, `rx`, `ry`, `rz`, `sx`, `sy`, `sz`, etc.
- Set `instanceop` on the geometryCOMP to point at the CHOP path
- Per-instance color via `instancecolormode`, `instancecolorr/g/b`
- See [reference.md](reference.md) for the full instancing recipe

### Feedback loop wiring order

1. Create feedback TOP early
2. Wire its OUTPUT into the processing chain first
3. Close the loop (connect its INPUT) LAST

## Reference

- Common operator types, recipes, and GLSL patterns: [reference.md](reference.md)
- Debugging common failures: [debugging.md](debugging.md)
