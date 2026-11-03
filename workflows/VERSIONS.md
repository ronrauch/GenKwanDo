# GenKwanDo master versions

Each version is a new saved Comfy Cloud record; older records are never overwritten. Times are Pacific.

| Version | Saved | File | What changed | Four-man band result |
|---|---|---|---|---|
| EASY v1 | 2026-11-03 01:59 PT | [genkwando-easy-v1.api.json](genkwando-easy-v1.api.json) | One image + one song in. Squaring, trim, Demucs stems, instrument naming and auto-written prompts all inside the graph; MASTER v4 render chain unchanged | Bassist p 0.055, drummer p 0.018, lips 0.531 (v4 0.484); brightness drift 49.4% (v4 39.7%), 25.7% after colour match. One cover tested; a second test was stopped by Cloud credits. |
| v4 | 2026-10-30 13:32 PT | [genkwando-master-v4.api.json](genkwando-master-v4.api.json) | 4-step turbo LoRA alone, res_multistep + kl_optimal at 8 steps, calm prompts, seed 210664234423221 fixed on all three windows | Bassist and drummer lock to their stems. Trumpeter, lips and a slow brightness drift still need work. |
| v3 | 2026-10-29 19:35 PT | [genkwando-master-v3.api.json](genkwando-master-v3.api.json) | Lip-motion LoRA + 8-step turbo LoRA, vocals and drums stems as references, counted prompts | Drummer locks; bassist off; a visible jump at the second window join. |

## Comps

A comp swaps one player's region in from another take of the same cover. The camera is locked and frame 0 is the cover in every take, so regions line up. Comps are made after rendering and are not part of a workflow.

| Comp | Made | File | How |
|---|---|---|---|
| Seven-piece band (take C, no comp) | 2026-11-02 17:40 PT | [seven-piece-30s.mp4](../examples/genkwando-30s/seven-piece-30s.mp4) | Six-piece plus a violinist; [genkwando-seven-piece-v1](genkwando-seven-piece-v1.api.json). Song written so violin and sax trade phrases; the shared "other" stem gated by time. Drummer locks in the first 10 s in all three takes (combined p 0.0002); the other players score no better than a still image, so nothing was comped. Joins 0.995 / 0.994, frame 0 match 0.992. |
| Garage rock (one render, no comp) | 2026-11-02 16:57 PT | [garage-rock-30s.mp4](../examples/genkwando-30s/garage-rock-30s.mp4) | New ACE-Step song and Z-Image cover, [genkwando-garage-rock-v1](genkwando-garage-rock-v1.api.json), colour matched at 0.5. Drummer p 0.017 over the piece; guitarist p 0.002 in the first 10 s only; bassist not locked (only 9 bass onsets). Lips r 0.631. Joins 0.988 / 0.992, frame 0 match 0.9945. One brightness flash at 20.1 s. |
| Six-piece band | 2026-10-31 00:42 PT | [six-piece-30s.mp4](../examples/genkwando-30s/six-piece-30s.mp4) | Four takes of [genkwando-six-piece-v1](genkwando-six-piece-v1.api.json); pianist and guitarist (section 1) and bassist (section 3) from their best takes, feathered masks. Locked: pianist, guitarist and bassist in those sections at p 0.001, drummer p 0.066. Sax not locked in any take. Best of 4 takes, so a single p near 0.05 is weak evidence. |
| Four-man band, colour matched (now band-30s.mp4) | 2026-10-30 18:07 PT | [band-30s.mp4](../examples/genkwando-30s/band-30s.mp4) | v4 render, every frame colour matched to the cover at strength 0.5 with [tools/colour_match.py](../tools/colour_match.py). Brightness drift 39.7% to 20.5%; bassist p 0.024, drummer p 0.013. Raw v4 render kept as [band-30s-v4.mp4](../examples/genkwando-30s/band-30s-v4.mp4). |
| Four-man band, bass comp | 2026-10-30 13:50 PT | [band-30s-comp.mp4](../examples/genkwando-30s/band-30s-comp.mp4) | v4 render as the base, bassist region from an earlier calm take, feathered mask |

## Tried after v4 (not adopted)

Each is one change from v4, scored the same way as v4. v4 itself was re-run from its saved Cloud record and reproduced the posted render (SSIM 0.997, PSNR 49.4 dB; bassist p 0.057, drummer p 0.014, the same as the posted take).

| Tried | When | Change | Result |
|---|---|---|---|
| v5b | 2026-10-30 18:07 PT | Demucs "other" stem (the trumpet) as a third audio reference for the trumpeter | Worse: trumpeter p 0.565 (v4 0.435), drummer p 0.093, brightness drift 69%, second window join 0.935, three jump frames. Rejected. |
| v5a | 2026-10-30 18:07 PT | Colour match of all 727 frames to the cover (KJNodes ColorMatchV2, reinhard, strength 0.5) before the final video | The Cloud worker failed twice at this run, so it is unproven in the workflow. Applied locally to the v4 frames (per-channel match, strength 0.5), it brings the brightness drift from 39.7% to 20.5% and keeps bassist p 0.024, drummer p 0.013 and separation 0.586. |
