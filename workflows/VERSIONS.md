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
