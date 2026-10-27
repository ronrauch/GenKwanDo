# Layers: a cover as a backdrop plus performers

```
SPLIT  ->  ANIMATE (per performer, per window)  ->  COMP  ->  ASSEMBLE
```

A performer is `{id, role, stem, lane, verb, person, image, matte, x, y, w, feather, audio, enabled}`.

| field | meaning |
|---|---|
| `role` | `singer`, `drums`, `bass`, `guitar`, `keys` |
| `stem` | which stem of a 6-stem separation belongs to them (`vocals`, `drums`, `bass`, `guitar`, `piano`, `other`); defaults from the role |
| `lane` | `h3-audio` (singer: the audio-driven graph), `h3` (instrument described in the prompt, **unproven**), `perfcap` (**not built**) |
| `image` | the clean image: the performer alone, a first frame, centre-cropped to a square at the render size |
| `matte` | white = performer, same framing as `image`. A PNG with alpha gives one automatically |
| `x`, `y`, `w` | where the performer's square sits on the cover canvas (1248 px) |
| `audio` | `mix` (the song slice drives H3) or `stem` (the stem slice does). Singer defaults to `mix`, the rest to `stem` |
| `enabled` | turn off to leave them static on the cover |

COMP overlays each animated performer on the cover (the backdrop), through the matte when there is one, feathered by
`feather` pixels. A performer that is not animated is simply still part of the cover.

**Limits.** The matte is static (cut from the clean first frame), so a performer who drifts outside it is clipped.
Stems are optional (`set_stems`, files named after the stem); without them an instrument is driven by the mix.
Splitting a cover automatically is a stretch goal and is not built.
