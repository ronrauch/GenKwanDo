# Plate Doctor

A VFX bench for one plate, built on ComfyUI and the Comfy Developer Platform.

**REMOVE** takes a performer or a prop out of a shot and rebuilds the set behind it, then wipes before to after: a
*vanish*. **RECOVER** turns an SDR plate into a gradeable HDR EXR sequence. **DIRECT** (scaffold, unproven) steers
water or motion along a path you draw. Outputs are the kind a compositor can use: a clean plate, a matte, EXR frames.

> Credit line: TODO: credit line, decided at ship
> (one-line edit in `plate_doctor/config.py`, constant `ATTRIBUTION`; `LICENSE` carries the same placeholder)

## Make yours in three steps

1. **Plate.** A video with an audio track, constant frame rate, both sides divisible by 32 (1280x544, 1920x1088).
2. **Matte.** A video or a numbered PNG folder, white = remove, from any roto or tracking tool. Empty frames are refused.
3. **Go.** Describe the *empty* set (never "remove the person"). The first screen's Go button is a dry run.

```bash
python3 -m plate_doctor demo                       # synthetic plate + matte, no network (workspace/demo/)
python3 -m plate_doctor serve                      # the web UI on a free local port
python3 -m plate_doctor remove plate.mp4 matte.mp4 --prompt-location "a bright studio, wooden chair, grey walls" --probe
```

That last command is a **dry run**: it plans the windows, cuts the window plates and mattes, writes the graphs to
`workspace/runs/<shot>_.../` and sends nothing. Add `--go` for a real render, starting with `--probe` (9 frames).

### Example output

<!-- EXAMPLE-OUTPUT-SLOT: replace this block with the first real Plate Doctor vanish clip (or a still from it),
     made from footage we own. Do not fake one. Until then this stays empty on purpose. -->
**No example yet.** This slot is reserved for the first real result. The synthetic demo only checks mechanics; its
"after" is a generated ground truth, not a Plate Doctor render, and is labelled that way in the UI.

## Running a real render

Plate Doctor submits through the **official Comfy SDK** by default, with raw HTTP as a fallback. Nothing is sent unless
you pass `--go`, and Comfy Cloud also needs a key.

```bash
pip install comfy-sdk            # optional extra, Python 3.10+. Not needed for the UI, the dry runs or the tests.
export COMFY_API_KEY=comfyui-...  # Comfy Cloud (a paid subscription is required for API access)
python3 -m plate_doctor remove plate.mp4 matte.mp4 --prompt-location "..." --probe --go
```

| Where | How |
|---|---|
| Comfy Cloud | `COMFY_API_KEY` set, nothing else |
| Local ComfyUI | `COMFY_BASE_URL=http://127.0.0.1:8188` (no key), with the models in `docs/MODELS.md` installed |
| No SDK installed | add `--transport http` for the raw-HTTP fallback |

The SDK path follows the public docs (`client.workflows.from_file`, `wf.set_input`, `client.assets.from_file`,
`client.run`, `job.get_outputs`). **Both transports are written but untested against a live server in this repo.**

## What each tab does

| Tab | Engine | Open weights? | State |
|---|---|---|---|
| REMOVE | LTX-2.5 22B distilled + the LTX-2.3 in/outpainting IC-LoRA, driven by your matte | yes | graph = a lab recipe proven on Comfy Cloud on a 9-frame probe; this app's wrapper around it is untested live |
| RECOVER (default lane) | LTX-2.3 HDR IC-LoRA, local ComfyUI graph | yes | the upstream flow is a working example; the API-format conversion here is **unproven** |
| RECOVER (`--lane ltx-api`) | hosted `api.ltx.video` HDR endpoint | **no, partner service** | needs `--partner-service-ok`, `LTX_API_KEY`, `--go`; untested |
| DIRECT | LTX IC-LoRA water-sim + motion-track | yes | scaffold only, see `docs/DIRECT.md` |

For an **Open Weights Only** category, use REMOVE and the RECOVER `graph` lane on local ComfyUI or your own pod: no
partner nodes, no hosted API.

## Rules the code enforces (each one cost somebody a bad render)

- Window planner: 8n+1 frames, at most 121 per job, overlap of at least 32 and a linear crossfade on long shots.
- The audio-reference wire (node 54 reads node 53, not node 42) is load-bearing; a recipe that "fixes" it is refused.
- Mattes: white = remove; PNG folders ordered numerically; content-hash file names refused (their sort order is not
  frame order); **empty frames refused per frame**, not by file count.
- Plates: sides divisible by 32, constant frame rate, an audio track (the recipe encodes it).
- A glossy floor or table needs its reflection in the matte: `python3 -m plate_doctor reflect plate.mp4 matte.mp4 --out matte_refl.mp4` (needs numpy).

## Install and test

Python 3.10+ and ffmpeg. No required third-party packages.

```bash
python3 -m unittest discover -s tests -t .
```

## Save to Comfy

See `docs/COMFY-SAVE.md`. Cost notes: `docs/COST.md`. Models: `docs/MODELS.md`.

Plate Doctor · v0.1.0 · 2026
