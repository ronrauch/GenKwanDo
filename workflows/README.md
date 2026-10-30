# GenKwanDo workflows

| File | What it is |
|---|---|
| [genkwando-master-v3.api.json](genkwando-master-v3.api.json) | The current master: cover + song in, 30 seconds out. Three chained MiniMax H3 windows at 1248, vocals and drums stems as references, a lip-motion LoRA stacked with the turbo LoRA, and counted, everything-moves prompts. Comfy API format. |

Load it in Comfy Cloud or ComfyUI, swap the LoadImage cover and the three LoadAudio files (song, vocals stem, drums stem), and run. The walkthrough of every node is in [examples/genkwando-30s](../examples/genkwando-30s/README.md).
