# Visual references

Eleven renderers were invented before this document existed. The brief each
time was "find other ideas", answered from imagination, and it showed: the
gallery read as eleven variations on *a field that reacts*, because that is
what kept getting reached for. The one look in the system that came from
outside it — `horizon`, which is vaporwave — is also the most identifiable tile
in the row.

So this is the list. It exists so the next round of style work starts from
something real rather than from a blank page, and so that "we already do that"
is a question with an answer.

Four of the looks below were gaps when this was written. Two became renderers
(`longhand`, `glitch`); two were built and then deleted, which is the more
useful lesson.

**A beat look is not a picture.** `rings`, `strata`, `scope`, `halftone`,
`spectrum`, `pulse_grid` and `swell` were seven renderers answering the question
"what picture goes next to the words", and the answer was that none does. What
was wanted was the beat visible *in the type* — it punches, it glows, it jolts.
So 7300 lines came out and `beat.py` went in: one chain after the word renderer,
presets as numbers.

The references below are still worth having. But a look being *identifiable* is
not the same as it being the right thing to build, and the question to ask of
the next one is not "can this be drawn" but "is this what the words should be
doing".

## What the system can and cannot draw

Worth stating first, because half the references below fail on it. A renderer
is a Script TOP writing pixels with numpy, plus Text TOPs drawing characters,
composited into a render chain. That means:

- **No footage.** There is no video input anywhere in the pipeline. Every
  reference whose look *is* the footage — live action, stock plates, shot
  performance — is out of reach, not merely expensive.
- **No instancing.** Unsupported on some of the Macs this has to run on, which
  rules out the usual particle and 3D-text routes.
- **Whole-array or nothing.** 720x1280 is a million pixels a frame; anything
  per-pixel in Python is not an option.
- **A Text TOP has one font size for its whole DAT.** Per-word scale needs
  either several Text TOPs or a Specification DAT, which places each row at its
  own pixel coordinate (origin lower-left).

## The references

### Type flying through 3D space

**The Chainsmokers, "Closer"** (official lyric video, Rory Kramer, 2016 — the
most-watched lyric video there is).

**Read it from frames, not from articles.** This reference was rebuilt three
times from written descriptions and was wrong every time; one look at a still
settled it. YouTube's page returns only navigation chrome to a fetcher, but its
generated frames are plain images and can be downloaded and viewed:

    https://img.youtube.com/vi/<id>/maxresdefault.jpg    the poster
    https://img.youtube.com/vi/<id>/{1,2,3}.jpg          25% / 50% / 75%
    https://img.youtube.com/vi/<id>/hq{1,2,3}.jpg        the same, larger

What four frames of this one show: thick white marker lettering sitting **flat
and large** over live-action footage — a couple indoors, a man with a camera in
golden grass, a couple silhouetted against a sunset, an aerial of a coastal
highway. A lyric phrase at a time, filling most of the frame width, stacked in
two or three rows with generous leading. Unmistakably drawn by hand: mixed caps
and lowercase inside a single word ("I CAN'4 Stop", "you CAN't AFFORD"),
letters of different sizes, a baseline that wanders. Over the brightest part of
the sunset the lettering still reads, and there is no outline or drop shadow —
the picture underneath is darkened instead.

The three wrong readings, written down because each looked right while it was
being built and each cost a renderer:

  * **`approach`** — words flying at the camera from a vanishing point.
  * **`longhand` v1** — a camera panning along one long handwritten line.
  * **`longhand` v2** — words scattered through a volume, camera drifting.

All three lean on one sentence, PremiumBeat's *"live action footage compiled
with lyrics that fly through 3d space"*. That describes the aerial shot alone,
where the lettering is tracked onto the landscape so it sits in the scene. The
type never moves through space. It sits there, and the drone moves.

→ **`longhand`**, which letters a phrase at a time, flat and big, in a marker
face with per-letter size, case and baseline variation, over the song's own
footage (`Track.plate`) or a generated stand-in when it has none.

### Footage playing inside the letters

Text used as a mask, with a moving texture showing through the glyphs — the
"mask with text and invert" look that recurs across lyric-video tutorials, and
works best with textural plates like water or foliage.

We have no plates, but we can generate the moving texture. → **`window`**.

### Neon grid, retro sun

The vaporwave vocabulary: CRT colours, a perspective grid, a banded sun, early-
internet iconography. → **`horizon`**.

### Glitch, scanlines, channel split

The other half of the vaporwave vocabulary, and the one we did not have:
intentional corruption as a visual signifier — CRT scanlines, RGB channels
pulled apart, blocks of the image displaced. Descends from demoscene glitch art.
→ **`glitch`**.

### Spectrum bars

The most recognisable music visual there is: vertical frequency bars, and its
variants — mirrored, and radial as a circular spectrum. Ubiquitous enough to be
invisible, which is exactly why its absence was conspicuous.

It needs data the system did not extract. Per-band energy over time now ships
alongside the drum onsets. → **`spectrum`**.

### Oscilloscope, Lissajous, XY

A continuous line tracing the waveform itself; in XY mode, Lissajous figures.
Retro and technical, and it reads as *measurement* rather than decoration.
→ **`scope`**.

### Radial pulses and rings

Rings of bars, circular waves, concentric pulses leaving a centre. → **`rings`**.

### Hard bands

Blocks of the frame struck one at a time — the most percussive of the
non-figurative looks. → **`strata`**.

### Halftone / dot screen

Print reproduction as an aesthetic: a regular lattice of dots whose size carries
the tone, each colour separation screened at its own angle. Reads instantly,
and it is a pure function of position and time, so it re-renders exactly.
→ **`halftone`**.

### Beat-synced type

Words snapping, stacking and pulsing onto the screen on the downbeat — the most
common lyric-video technique of all, and less a look than a timing discipline
every lyric renderer here already follows through the cue table.
→ every `lyric` renderer.

## Out of reach, and why

| Reference | Why not |
|---|---|
| Live action, stock plates, performance | no video input in the pipeline |
| Icon storytelling (Katy Perry "Roar", Dua Lipa "Levitating") | needs drawn assets, not a generative field |
| Stop-motion / handmade (Jason Mraz) | the whole point is that it is photographed |
| Old Hollywood poster (Kelly Clarkson) | type-led but essentially static; a preview has to move |
| Particle explosions on the drop | instancing, unsupported on some target Macs |
| Liquid / morphing letterforms | needs glyph outlines; a Text TOP gives pixels |

## Sources

- [Mood board: 13 great lyric video examples](https://creative-commission.com/news/mood-board-13-great-lyric-video-examples)
- [50 kinetic typography examples](https://www.svgator.com/blog/50-kinetic-typography-examples/)
- [What is kinetic typography](https://genesismotiondesign.com/what-is-kinetic-typography/)
- [Create your own lyric videos](https://www.premiumbeat.com/blog/create-lyric-videos-after-effects/)
- [Audio reactive visualizers in TouchDesigner](https://derivative.ca/community-post/tutorial/audio-reactive-visualizers-touchdesigner/72251)
- [Vaporwave — Aesthetics Wiki](https://aesthetics.fandom.com/wiki/Vaporwave)
