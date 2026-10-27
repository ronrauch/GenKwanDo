# Cost

This repo ships **no price**. `--dry-run` prints "Cost estimate: PLACEHOLDER" on purpose.

What exists: one measurement from the author's single run of the REMOVE recipe on Comfy Cloud (RTX 6000 Pro class):
a 9-frame 1280x544 probe took 16.3 GPU-seconds. A long shot is one job per window of at most 121 frames, so cost
scales with window count. That is one data point, not a quote.

How to get your own number: run `--probe --go`, read the job's GPU-seconds from your billing page, multiply by the
window count that `--dry-run` printed. Comfy Cloud API access needs a paid subscription; the hosted LTX HDR lane
bills your LTX credits per second of input video.
