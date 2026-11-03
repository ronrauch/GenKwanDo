# GenKwanDo workflows

| File | What it is |
|---|---|
| [genkwando-easy-v1.api.json](genkwando-easy-v1.api.json) | **The easy one.** Load one image and one song, press Run. The graph squares the image to 1248 (upscaling small covers), trims the song to 30 s, splits the stems, names the instruments it hears, writes the three prompts from the cover, then renders with the MASTER v4 chain. Tested once, on the four-man band. The instrument naming and auto-prompts use Google Gemini, a paid partner node, not open source. Notes: [EASY-v1-NOTES.md](EASY-v1-NOTES.md). |
| [genkwando-master-v4.api.json](genkwando-master-v4.api.json) | The current master, and the one that made the four-man band video. Cover + song in, 30 seconds out: three chained MiniMax H3 windows at 1248, vocals and drums stems as references, the 4-step turbo LoRA, res_multistep with kl_optimal at 8 steps, seed 210664234423221 on every window, and calm, restrained prompts. Comfy API format. |
| [genkwando-six-piece-v1.api.json](genkwando-six-piece-v1.api.json) | The six-piece band: MASTER v4 settings with six players. Demucs htdemucs_6s on Comfy Cloud returns 4 stems (vocals, drums, bass, other), so the sax rides "other" and guitar and piano share the leftover. Comfy API format. |
| [genkwando-seven-piece-v1.api.json](genkwando-seven-piece-v1.api.json) | The seven-piece band: MASTER v4 settings, seven players, and the violin-and-sax "other" stem as a third audio reference. Comfy API format. |
| [genkwando-garage-rock-v1.api.json](genkwando-garage-rock-v1.api.json) | The garage rock piece: MASTER v4 settings unchanged, with new prompts for a singer, guitarist, bassist and drummer. Comfy API format. |
| [genkwando-master-v3.api.json](genkwando-master-v3.api.json) | The previous master: the same chain with a lip-motion LoRA stacked on the 8-step turbo LoRA and counted, everything-moves prompts. Kept for comparison. |

Load one in Comfy Cloud or ComfyUI, swap the LoadImage cover and the three LoadAudio files (song, vocals stem, drums stem), and run. The walkthrough of every node is in [examples/genkwando-30s](../examples/genkwando-30s/README.md).

Version history with save times: [VERSIONS.md](VERSIONS.md).
