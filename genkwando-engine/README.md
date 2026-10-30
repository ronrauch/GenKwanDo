# Cutting Room Lite

**Pick an album cover and 30 seconds of a song. Get a music video.** Built on the Comfy Developer
Platform with MiniMax H3: the song drives the picture, so a singer's lips follow the vocal.

> **EXAMPLE OUTPUT: NOT YET RENDERED.**
> This slot is reserved for a real result (cover, song slice and the finished clip, all original).
> Nothing is shown here on purpose: no mock-up, no stand-in. It gets filled once a real render exists.
>
> `[ example clip and its cover go here ]`

## Make yours in three steps

1. **Cover.** Pick a square cover image. Say what is on it: a performer, an object, or a landscape.
2. **Song.** Pick a song. Click the waveform to place a 30 second slice.
3. **Go.** The app plans the render (3 windows of about 10 s), builds the ComfyUI graph for each, and shows you
   every take. Approve one per window, or re-roll the seed. Then it assembles the cut with your original song.

## One performer, or the whole band

With no layers, the whole cover is animated as one picture (a singing portrait, a moving still life, a drifting
landscape). For a cover with several people, the app models the cover as layers:

| Stage | What happens | Status in v0.1 |
|---|---|---|
| SPLIT | one clean image per performer (the performer alone, a first frame) | **you supply them.** Splitting a cover automatically (image-edit model plus a matte) is a documented stretch, not built |
| ANIMATE | per performer, per window. **Singer:** the H3 audio-driven graph, the song as `ref_audio` | the singer recipe follows a graph its author ran end to end; this app has not submitted anything yet |
| | **Instruments** (drums, bass, guitar, keys): described in the prompt, lane `h3` | **UNPROVEN.** See the drummer test below |
| | Instruments by performance capture, lane `perfcap` | **documented only, not built** |
| COMP | each animated performer is overlaid back on the cover at its position and size, through a matte or alpha | built and tested with synthetic layers |
| BEAT | **beat objects** (a drum, speaker, amp or vinyl shown as an object) pulse, flash, sway or glow to their stem. A visual effect on a still image, applied in COMP: no render, no GPU, no cost. **Not a played instrument** | built and tested on synthetic stems |
| ASSEMBLE | the original song slice goes under the finished picture | built and tested |

Performers you do not animate stay as they are on the cover. A clean PNG with an alpha channel doubles as the
matte. Our rule: an audio model moves a face, never sticks or hands. That is why instruments are a lane that must
earn its place; see [docs/LAYERS.md](docs/LAYERS.md) and [docs/DRUMMER-TEST.md](docs/DRUMMER-TEST.md).

## Setup

Requirements: Python 3.10+, `ffmpeg` and `ffprobe` on your PATH. The app itself needs nothing else.

```bash
git clone <this repo> && cd cutting-room-lite
python3 -m cutting_room_lite serve --root my-project        # dry run: nothing is sent anywhere
# open http://127.0.0.1:8800
```

### Going live (this spends credits)

Everything is a dry run until you pass `--go`. A dry run writes the ComfyUI graph and the audio chunk for every
window under `takes/`, and prints the plan and window count first. A live run needs both:

- `--go` on the command, and
- for Comfy Cloud, `COMFY_API_KEY` in the environment (key from the Comfy platform). A local ComfyUI needs `--go` but no key.

```bash
export COMFY_API_KEY=...                       # never put the key on the command line
python3 -m cutting_room_lite serve --root my-project --go                       # Comfy Cloud
python3 -m cutting_room_lite serve --root my-project --go --backend local       # your own ComfyUI
```

**Submit path.** The documented primary path is the official Comfy Python SDK (`comfy_sdk`), an optional extra:

```bash
pip install -r requirements-sdk.txt            # comfy-sdk; without it the stdlib HTTP fallback is used
```

`--transport sdk|http|auto` picks the route (default `auto`: the SDK if installed, else HTTP). Set `COMFY_BASE_URL`
to point at a Comfy API deployment or a local ComfyUI (default is Comfy Cloud). Both routes sit behind the same gate
and **neither has been run against the network in this version.**

**Local run on your own GPU.** The graph uses the MiniMax H3 reference-to-video weights from the Comfy-Org H3 repo
(the int8 `ref2va` model, the 4-step turbo LoRA, the Qwen3-VL text encoder, the H3 video and audio VAEs; filenames are
in `cutting_room_lite/graphs/h3_ref2va_window.template.json`). Start ComfyUI with those in place and use
`--backend local`. H3 is a large model: plan for a high-VRAM card.

## Command line

```bash
python3 -m cutting_room_lite plan --length 30                       # print the window plan
python3 -m cutting_room_lite synthetic --root demo                  # test song + placeholder layers, no network
python3 -m cutting_room_lite render --root demo                     # dry run (add --go to spend)
python3 -m cutting_room_lite assemble --root demo
python3 -m cutting_room_lite drummer-test --cover c.png --song s.wav --bpm 120
python3 -m cutting_room_lite --about
```

## How a window works

Each window is its own ComfyUI job so one can be re-rolled. Window 0 uses the clean image as both the reference and
the frame-0 guide. Later windows keep that image as the reference and start from the **last frame of the previous
approved take**. They render one extra leading frame (the repeated guide frame) that assembly drops, and their
audio chunk starts one frame early to match. The graph settings come from a graph that was run for a singing
close-up: `res_multistep`, `kl_optimal`, 8 steps with the 4-step turbo LoRA, 1248x1248, 24 fps.

## What is proven and what is not

- **Built and tested here:** window planning, graph building, audio trimming, the spend gate, dry runs, the web app,
  layers, COMP with mattes, assembly to the exact slice length. 124 tests, no network.
- **Not run here:** any real submit, on either route (SDK or HTTP). Audio upload to Comfy Cloud is unconfirmed (the
  docs describe the upload endpoint for images). A third chained window is untested (the reference graph chained two).
- **Unproven:** instruments playing their parts through H3. Run the drummer test first.
- **Not built:** auto-splitting a cover, the performance-capture lane, matte tracking (the matte is static: it is the
  matte of the clean first frame). Beat objects are tested on synthetic stems, not yet on real music.

## Tests

```bash
pip install -r requirements-dev.txt && python3 -m pytest
```

## Saving the graph in Comfy

See [docs/COMFY-SAVE.md](docs/COMFY-SAVE.md).

## About

Cutting Room Lite
TODO: credit line, decided at ship
v0.1.0 · 2026 · MIT licence (see LICENSE)
