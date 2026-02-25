# Debugging TouchDesigner Projects

## Quick Diagnosis

| Symptom | Likely Cause | Fix |
|---|---|---|
| Black screen | Shader compile error, missing connection, wrong resolution | `inspect` on the output chain — look for `errors` |
| Operator not found | Relative path used instead of absolute | Use `/project1/my_op`, not `my_op` |
| Param didn't take | Wrong parameter name | `inspect` to see current values, `docs` to get correct name |
| Expression error | String assigned to numeric par | Use `.expr = "..."` for expressions, not direct assignment |
| Uniform not working | Name mismatch or missing wiring | Check `vec0name` matches GLSL `uniform` declaration exactly |
| Feedback loop frozen | Loop not closed, or no decay | Verify feedback input is connected; ensure scale < 1.0 or brightness < 1.0 |
| Duplicate operators | Re-ran script without cleanup | Use `create` tool (auto-replaces), or add destroy loop in `run` scripts |
| Observe shows wrong output | Auto-detection grabbed wrong TOP | Pass explicit `top` path to `observe` |
| TOP stuck at 128x128 | Missing `outputresolution='custom'` or `resmult=False` | Set both + explicit `resolutionw/h`; destroy+recreate if stuck |
| Resolution smaller than expected | Global res multiplier active | Set `resmult=False` on the affected TOP |
| Instances not showing | Wrong `instanceop` path or missing channels | `inspect` geometryCOMP Instance page; verify CHOP has `tx`, `ty`, `tz` channels |

## Diagnosis Steps

### 1. Check for errors
```
inspect: path="/project1/my_op"
```
Look for `errors` and `warnings` fields in the response.

### 2. Verify connections
```
map: path="/project1"
```
Check that edges (connections) match your intended signal flow.

### 3. Check param values
```
run: code="op('/project1/my_op').par.rotate.val"
```
Verify the parameter actually has the value you set.

### 4. Check if expression is valid
```
run: code="op('/project1/my_op').par.rotate.expr"
```
Returns the expression string, or empty if none set.

### 5. Isolate shader errors
If a GLSL TOP has errors, read the pixel DAT to check the shader source:
```
read: path="/project1/my_glsl_pixel"
```
Then check the GLSL TOP for compile errors:
```
inspect: path="/project1/my_glsl"
```

## Common `run` Errors

- **`NameError: name 'glslTOP' is not defined`** — You're using a type constant that doesn't exist. Use `docs(type='list_types')` to find the correct name.
- **`TypeError: 'NoneType' object...`** — An `op()` call returned None. The operator doesn't exist at that path.
- **`AttributeError: ... has no attribute 'par'`** — You're calling `.par` on None. Check that the operator exists first.
- **`td.error: Can't set ... to string`** — You assigned a string to a numeric parameter. Use `.expr` instead.

## Render Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| No frames recorded (0 PNGs) | Timeline not playing | Ensure TD is in play mode — `render` needs the timeline running to capture frames |
| `ffmpeg not found` | ffmpeg not on PATH | Install ffmpeg (`brew install ffmpeg` on macOS) or check that it's in a standard location |
| Audio missing from MP4 | Wrong `audio_chop` path | `inspect` the CHOP path to verify it exists and has audio channels |
| Recording never stops | Duration too long or timeline reset | Check that nothing else resets the timeline during recording |
| Short/truncated video | Timeline looped during recording | `render` auto-extends the timeline, but check that nothing else resets it |

## Observe Side Effects

`observe` advances `me.time.frame` by several frames per captured frame. This is normally fine for visual work, but be aware if timeline position matters for your project logic.
