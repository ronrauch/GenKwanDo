# GenKwanDo master versions

Each version is a new saved Comfy Cloud record; older records are never overwritten. Times are Pacific.

| Version | Saved | File | What changed | Four-man band result |
|---|---|---|---|---|
| v4 | 2026-10-30 13:32 PT | [genkwando-master-v4.api.json](genkwando-master-v4.api.json) | 4-step turbo LoRA alone, res_multistep + kl_optimal at 8 steps, calm prompts, seed 210664234423221 fixed on all three windows | Bassist and drummer lock to their stems. Trumpeter, lips and a slow brightness drift still need work. |
| v3 | 2026-10-29 19:35 PT | [genkwando-master-v3.api.json](genkwando-master-v3.api.json) | Lip-motion LoRA + 8-step turbo LoRA, vocals and drums stems as references, counted prompts | Drummer locks; bassist off; a visible jump at the second window join. |

## Comps

A comp swaps one player's region in from another take of the same cover. The camera is locked and frame 0 is the cover in every take, so regions line up. Comps are made after rendering and are not part of a workflow.

| Comp | Made | File | How |
|---|---|---|---|
| Four-man band, bass comp | 2026-10-30 13:50 PT | [band-30s-comp.mp4](../examples/genkwando-30s/band-30s-comp.mp4) | v4 render as the base, bassist region from an earlier calm take, feathered mask |

## Tried after v4 (not adopted)

Each is one change from v4, scored the same way as v4. v4 itself was re-run from its saved Cloud record and reproduced the posted render (SSIM 0.997, PSNR 49.4 dB; bassist p 0.057, drummer p 0.014, the same as the posted take).

| Tried | When | Change | Result |
|---|---|---|---|
| v5b | 2026-10-30 18:07 PT | Demucs "other" stem (the trumpet) as a third audio reference for the trumpeter | Worse: trumpeter p 0.565 (v4 0.435), drummer p 0.093, brightness drift 69%, second window join 0.935, three jump frames. Rejected. |
| v5a | 2026-10-30 18:07 PT | Colour match of all 727 frames to the cover (KJNodes ColorMatchV2, reinhard, strength 0.5) before the final video | The Cloud worker failed twice at this run, so it is unproven in the workflow. Applied locally to the v4 frames (per-channel match, strength 0.5), it brings the brightness drift from 39.7% to 20.5% and keeps bassist p 0.024, drummer p 0.013 and separation 0.586. |
