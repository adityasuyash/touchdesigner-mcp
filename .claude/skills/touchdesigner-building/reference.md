# TouchDesigner Reference

Sources: [Par Class](https://docs.derivative.ca/Par_Class), [Connector Class](https://docs.derivative.ca/Connector_Class), [Working with OPs in Python](https://docs.derivative.ca/Working_with_OPs_in_Python), [GLSL TOP](https://docs.derivative.ca/GLSL_TOP), [Introduction to Python Tutorial](https://docs.derivative.ca/Introduction_to_Python_Tutorial)

## Python API Essentials

### Operator References
```python
op('/project1/my_op')       # absolute path (always works from MCP)
root.op('child_name')       # relative to a container
root.children               # list all children
root.create(glslTOP, 'name') # create operator (returns reference)
my_op.destroy()              # delete operator
```

Always check existence before accessing: `if op('/project1/foo'):` — `op()` returns `None` for missing paths.

### Connecting Operators ([Connector Class](https://docs.derivative.ca/Connector_Class))

Connections go through `.inputConnectors` and `.outputConnectors`:

```python
# Connect output of noise1 to input 0 of lag1
op('noise1').outputConnectors[0].connect(op('lag1'))

# Connect to a specific input (e.g. 2nd input of composite)
op('src').outputConnectors[0].connect(op('comp').inputConnectors[1])

# Shorthand: connect input to a source op (replaces existing connection)
op('comp').inputConnectors[0].connect(op('src'))

# Disconnect
op('lag1').inputConnectors[0].disconnect()
```

**Input connectors replace** the existing connection. **Output connectors append** to the target.

### Parameter Access ([Par Class](https://docs.derivative.ca/Par_Class))

| Access | Does | Use When |
|---|---|---|
| `par.x = 5` | Sets constant value | Static values |
| `par.x.expr = "..."` | Sets expression (auto-enters expression mode) | Dynamic/animated values |
| `par.x.val` | Get/set constant mode value only | You know it's constant mode |
| `par.x.eval()` | Get current value in any mode | Reading values safely |

Menu params accept names or indices: `par.operand = 'screen'` or `par.operand = 28`.

### Resolution Management

TOPs inherit resolution from their first input. Problems happen at **chain roots** (TOPs with no input) and **feedbackTOPs** that haven't resolved yet. Set resolution explicitly on these:

```python
top.par.outputresolution = 'custom'   # override inheritance
top.par.resmult = False               # ignore global resolution multiplier
top.par.resolutionw = 1920
top.par.resolutionh = 1080
```

**Which TOPs need this:** feedbackTOP (defaults to 128x128), noiseTOP, constantTOP, glslTOP, renderTOP — any TOP at the start of a chain with no input. Mid-chain TOPs inherit correctly if wired after the source has its resolution set. If resolution is wrong after setting params, destroy and recreate the operator.

### Operator Paths
- Always absolute from MCP: `/project1/my_op`
- `me` refers to the script's owner operator (inside TD)
- `me.parent()` goes up one level
- `me.time.seconds` and `me.time.frame` for time values in expressions

## Commonly Used Operator Types

Type constants are Python globals in TD, not strings. Always verify with `docs(type='list_types', family=...)`.

### TOPs (Texture Operators)

| Type Constant | What It Does | Key Params |
|---|---|---|
| `glslTOP` | Custom shaders. Auto-creates `_pixel` DAT | `resolutionw/h`, `vec0name`, `vec0valuex/y/z/w` |
| `compositeTOP` | Blend two inputs | `operand` (menu: `screen`, `add`, `multiply`, `over`, etc.) |
| `feedbackTOP` | Feedback loop node | `top` (target), `resetpulse` |
| `transformTOP` | Translate/rotate/scale | `tx/ty`, `rotate`, `sx/sy`, `extend` |
| `levelTOP` | Brightness/gamma/contrast | `brightness1`, `gamma1`, `contrast`, `invert` |
| `hsvadjustTOP` | Hue/saturation/value | `hueoffset`, `saturationmult`, `valuemult` |
| `blurTOP` | Blur filter | `size` (filter size), `type` |
| `noiseTOP` | Procedural noise texture | `type`, `rough`, `period`, `amp`, `tx/ty/tz` (animate!) |
| `nullTOP` | Pass-through / output reference | (no special params) |
| `constantTOP` | Solid color | `colorr/g/b`, `alpha` |
| `renderTOP` | 3D render | `camera`, `geometry`, `lights`, `resolutionw/h` |
| `moviefileinTOP` | Load image/video | `file` |
| `switchTOP` | Switch between inputs | `index` |
| `textTOP` | Render text | `text`, `fontsizex` |
| `cropTOP` | Crop region | `cropleft/right/top/bottom` |
| `rampTOP` | Color ramp/gradient | (various ramp params) |

### CHOPs (Channel Operators)

| Type Constant | What It Does | Key Params |
|---|---|---|
| `lfoCHOP` | Oscillator | `wavetype` (menu: `sin`, `tri`, `ramp`, `square`), `frequency`, `amp` |
| `noiseCHOP` | Procedural noise | `rough`, `period`, `amp`, `channelname` |
| `mathCHOP` | Range mapping / math | `gain`, `preoff`, `postoff`, `fromrange1/2`, `torange1/2` |
| `mergeCHOP` | Combine channels | (connect multiple inputs) |
| `constantCHOP` | Static values | `name0`, `value0` |
| `filterCHOP` | Smooth/lag values | `filter`, `width` |
| `selectCHOP` | Reference another CHOP | `chop` |

### SOPs, MATs, COMPs

| Type Constant | What It Does |
|---|---|
| `gridSOP`, `sphereSOP`, `boxSOP`, `torusSOP` | Primitive geometry |
| `noiseSOP` | Deform geometry with noise |
| `pbrMAT`, `phongMAT`, `constantMAT` | Materials for 3D rendering |
| `geometryCOMP` | Contains SOPs for rendering |
| `cameraCOMP` | Camera for renderTOP |
| `lightCOMP` | Light for renderTOP |

## Recipes

### GLSL Shader Pipeline

```python
root = op('/project1')
glsl = root.create(glslTOP, 'my_glsl')
glsl.par.resolutionw = 1920
glsl.par.resolutionh = 1080

out = root.create(nullTOP, 'out')
out.inputConnectors[0].connect(glsl)

# Write shader to auto-created pixel DAT
pixel_dat = root.op('my_glsl_pixel')
pixel_dat.text = """uniform vec4 uTime;
out vec4 fragColor;
void main() {
    vec2 res = uTDOutputInfo.res.zw;
    vec2 uv = gl_FragCoord.xy / res;
    fragColor = vec4(uv, 0.5 + 0.5 * sin(uTime.x), 1.0);
}"""

# Wire time uniform manually
glsl.par.vec0name = 'uTime'
glsl.par.vec0valuex.expr = "me.time.seconds"
```

### Feedback Loop

```python
root = op('/project1')

# Seed content
seed = root.create(noiseTOP, 'fb_seed')
seed.par.resolutionw = 960
seed.par.resolutionh = 540

# Feedback — create early
feedback = root.create(feedbackTOP, 'fb_feedback')

# Processing chain off feedback output
transform = root.create(transformTOP, 'fb_transform')
transform.par.rotate.expr = "me.time.seconds * 2"
transform.par.sx = 0.99
transform.par.sy = 0.99
transform.inputConnectors[0].connect(feedback)

# Composite seed + feedback
comp = root.create(compositeTOP, 'fb_comp')
comp.par.operand = 'screen'
comp.inputConnectors[0].connect(seed)
comp.inputConnectors[1].connect(transform)

# Output
out = root.create(nullTOP, 'fb_out')
out.inputConnectors[0].connect(comp)

# Close the loop LAST
feedback.inputConnectors[0].connect(comp)
```

### 3D Render Pipeline

```python
root = op('/project1')

geo = root.create(geometryCOMP, 'geo1')
torus = geo.create(torusSOP, 'torus1')
out_sop = geo.create(outSOP, 'out1')
out_sop.inputConnectors[0].connect(torus)

cam = root.create(cameraCOMP, 'cam1')
cam.par.tz = 5

light = root.create(lightCOMP, 'light1')

mat = root.create(pbrMAT, 'mat1')
geo.par.material = 'mat1'

render = root.create(renderTOP, 'render1')
render.par.camera = 'cam1'
render.par.geometry = 'geo1'
render.par.lights = 'light1'
render.par.outputresolution = 'custom'
render.par.resmult = False
render.par.resolutionw = 1920
render.par.resolutionh = 1080
```

**Key 3D param names** (use `docs` to verify):

| Operator | Params |
|---|---|
| renderTOP | `camera`, `geometry`, `lights`, `antialias`, `bgcolorr/g/b`, `cullface` |
| cameraCOMP | `tx/ty/tz`, `rx/ry/rz`, `fov`, `near`, `far` |
| lightCOMP | `tx/ty/tz`, `lighttype` (menu), `dimmer`, `lightcolorr/g/b` |

### Instanced 3D Scene

Use TD's native instancing on `geometryCOMP` for efficiently rendering many copies of the same geometry with different transforms/colors:

```python
root = op('/project1')

# Instance data — CHOP with channels named tx, ty, tz, sx, sy, sz, etc.
inst_data = root.create(constantCHOP, 'inst_data')
inst_data.par.name0 = 'tx'
inst_data.par.value0 = 0
inst_data.par.name1 = 'ty'
inst_data.par.value1 = 0
inst_data.par.name2 = 'tz'
inst_data.par.value2 = 0

# Geometry with instancing enabled
geo = root.create(geometryCOMP, 'geo_inst')
box = geo.create(boxSOP, 'box1')
out_sop = geo.create(outSOP, 'out1')
out_sop.inputConnectors[0].connect(box)

# Instance page params (on geometryCOMP, NOT renderTOP)
geo.par.instanceop = 'inst_data'
geo.par.instancetx = 'tx'
geo.par.instancety = 'ty'
geo.par.instancetz = 'tz'
# Optional: per-instance rotation and scale
# geo.par.instancerx = 'rx'
# geo.par.instancesx = 'sx'

# Optional: per-instance color
# geo.par.instancecolormode = 'instancecolor'
# geo.par.instancecolorr = 'cr'
# geo.par.instancecolorg = 'cg'
# geo.par.instancecolorb = 'cb'

mat = root.create(pbrMAT, 'mat_inst')
geo.par.material = 'mat_inst'

cam = root.create(cameraCOMP, 'cam_inst')
cam.par.tz = 10

light = root.create(lightCOMP, 'light_inst')

render = root.create(renderTOP, 'render_inst')
render.par.camera = 'cam_inst'
render.par.geometry = 'geo_inst'
render.par.lights = 'light_inst'
render.par.outputresolution = 'custom'
render.par.resmult = False
render.par.resolutionw = 1920
render.par.resolutionh = 1080
```

**Instance page params** are on `geometryCOMP` — use `docs(type='geometryCOMP', filter='instance')` to see them all. The CHOP must have one sample per instance with channel names matching what you set in `instancetx`, `instancety`, etc.

## GLSL in TouchDesigner

Per the [GLSL TOP docs](https://docs.derivative.ca/GLSL_TOP):

### How the GLSL TOP Works

- Creating a `glslTOP` named `my_glsl` auto-creates `my_glsl_pixel` (pixel shader DAT) and `my_glsl_compute` (compute shader DAT)
- Write your shader to the `_pixel` DAT's `.text` property
- Color output: declare `out vec4 fragColor;` (or any name with `layout(location = 0)`)
- TD prepends its own uniform/function declarations before your code — so `#extension` directives must go in the Preprocess Directives param (`predat`), not in the main shader

### Built-in Uniforms (always available)

- `uTDOutputInfo.res.zw` — output resolution (width, height)
- `gl_FragCoord.xy` — pixel coordinates
- `TDSimplexNoise()` — built-in noise function (Performance or Quality mode via `simplexnoise` param)

### Standard UV Patterns

```glsl
vec2 res = uTDOutputInfo.res.zw;
vec2 uv = gl_FragCoord.xy / res;                                    // 0..1
vec2 centered = (gl_FragCoord.xy - 0.5 * res) / min(res.x, res.y); // centered, aspect-correct
```

### Custom Uniforms — Wiring

Uniform types map to GLSL TOP parameter pages:

| GLSL Type | Param Page | Param Pattern |
|---|---|---|
| `uniform vec4 uFoo;` | Vectors | `vec0name='uFoo'`, `vec0valuex/y/z/w` |
| `uniform float uBar[N];` | Arrays | `array0name='uBar'`, `array0chop` (CHOP source) |
| `uniform mat4 uMat;` | Matrices | `matrix0name='uMat'`, `matrix0value` (CHOP) |
| `uniform vec4 uColor;` | Colors | `color0name='uColor'`, `color0rgbr/g/b`, `color0alpha` |

Common wiring patterns:
```python
# Time
glsl.par.vec0name = 'uTime'
glsl.par.vec0valuex.expr = "me.time.seconds"

# CHOP channels
glsl.par.vec0name = 'uAudio'
glsl.par.vec0valuex.expr = "op('my_chop')['chan1']"

# Input textures: connect TOPs to GLSL inputs
# Access in shader as sTD2DInputs[0], or use sampler uniforms
```

### Debugging Shaders

- Use an **Info DAT** with its Operator param pointing at the GLSL TOP to see compile errors
- "Compiled Successfully" / "Linked Successfully" = no errors
- Unused uniforms are stripped by the compiler and won't appear in Load Uniform Names

## Tool Cheat Sheet

| Goal | Tool |
|---|---|
| See what exists + positions | `map` (shows `@(x,y)` on every node) |
| Render MP4 video | `render` with `output` + `duration` (both required), optional `fps` and `audio_chop` for audio capture |
| Look up param names | `docs` with type constant |
| Find type constants | `docs` with `type='list_types'` |
| Create/wire operators | `create` (single op, requires `nodeX`/`nodeY`) or `run` (multi-op scripts) |
| Set params (validated) | `set` with `params` and/or `exprs` |
| Quick value check | `run` (expressions return values directly) |
| Read shader/script | `read` |
| Write shader/script | `write` |
| Tweak shader/script | `edit` |
| See visual output | `observe` (pass explicit `top` path) |
| Check operator state | `inspect` |
