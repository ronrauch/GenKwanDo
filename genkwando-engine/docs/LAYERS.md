# Layers: a cover as a backdrop plus performers

```
SPLIT  ->  ANIMATE (per performer, per window)  ->  COMP  ->  ASSEMBLE
```

A performer is `{id, role, stem, lane, verb, person, image, matte, x, y, w, feather, audio, enabled}`.

| field | meaning |
|---|---|
| `role` | `singer`, `drums`, `bass`, `guitar`, `keys` (players), or `beat` (an object that pulses to a stem) |
| `stem` | which stem of a 6-stem separation belongs to them (`vocals`, `drums`, `bass`, `guitar`, `piano`, `other`); defaults from the role |
| `lane` | `h3-audio` (singer: the audio-driven graph), `h3` (instrument described in the prompt, **unproven**), `perfcap` (**not built**), `comp` (beat objects only: a COMP effect) |
| `effect`, `strength`, `decay` | beat objects only: `pulse` / `flash` / `sway` / `glow`, strength 0..1, decay in seconds (0 = the effect's default) |
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

## Beat objects: a visual effect on a still object

Some covers show an instrument as an **object**: a drum, a speaker, an amp, a vinyl record. Those become a layer of
kind `beat`. Be clear about what this is:

> **A beat object is a visual effect applied to a still image. It is not a played instrument.** Nothing is
> rendered, no hands move, no sticks land. The object pulses, flashes, sways or glows with its stem, the way a
> speaker cone or a stage light would. Players (hands on instruments) are a different thing and remain the
> **UNPROVEN** lane (prompted through H3, see DRUMMER-TEST.md) or the **not built** performance-capture lane.

It runs in the COMP stage only, so it costs nothing: no GPU, no network, no credits.

| effect | meant for | what it does | default decay |
|---|---|---|---|
| `pulse` | kick | the object scales up on each hit (to +30% at strength 1) and settles | 0.18 s |
| `flash` | snare | brightness flash plus a small shake on each hit | 0.10 s |
| `sway` | bass | rotation and drift that follow the stem's loudness | 0.30 s |
| `glow` | held notes | brightness (and a hint of scale) that follows the stem's loudness | 0.25 s |

**How it works.** ffmpeg decodes the stem (the performer's `stem`, or the whole mix if no stem is loaded) to mono
PCM, band-filtered for the effect (lows for kick, highs for snare). Python (stdlib only, no librosa, no torch) turns
that into per-hop energy, then onset times (a jump in log-energy, with a minimum gap so one hit counts once) and a
per-frame loudness envelope. Per-frame transforms (zoom, angle, brightness, dx, dy) come from those, deterministically.
`media.comp_cmd` writes them into the ffmpeg filter graph as expressions (`zoompan`, `rotate`, `eq`, `overlay`).

**Safety clamps.** The layer's square never leaves the cover (dx, dy are limited by the square's position), zoom
stays between 1.0 and 1.5, rotation within 0.2 rad, brightness within +/-0.5. The pulse grows the object inside its
own square, so leave margin around the object in its image (or use a PNG with transparent margin), and use a matte if
the object is not a full square.

**Limits.** Onset detection is energy-based: it finds clear hits in a drum stem, and will be less sure on dense or
washed-out material. With no stem loaded, a beat object rides the whole mix, which is rougher. The matte and the
object are one still: it does not track anything. Tested on synthetic click, kick and hum stems, not yet on real music.
