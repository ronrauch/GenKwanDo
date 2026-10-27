# DIRECT (scaffold, UNPROVEN in this repo)

Idea: draw a trajectory over the plate and let LTX IC-LoRAs (water-sim + motion-track) follow it.

Known from hand-run experiments (not reproduced by this code):
- Base must be the LTX-2.3 22B **dev** checkpoint plus the 384 distilled LoRA at 0.5, never the distilled checkpoint
  (IC-LoRA output then copies its guide video).
- Stage 1 at native resolution only (about 1280x704); a second pass upscales and refines with no IC-LoRA.
- Iterate on low-res wedges, one knob per round, before paying for a full-resolution pass.

Missing for v0.1: a stroke-drawing UI, the track-to-guide encoder, and a converted API graph. Nothing in the app
submits this lane.
