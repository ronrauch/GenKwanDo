# Saving the graph into Comfy

The window graph must live in the Comfy workspace as a named, documented workflow, not only as JSON in this repo.

**Not done yet.** Nothing has been saved. Do this at ship:

1. Name: `SECRETLAB-H3-CutRoomLite-v001`.
2. Build the saved (canvas) format with the lab's `secretlab_save.py`, so the Note nodes with the authorship line and
   the date are on the canvas. Saving the API JSON inline silently drops them: a note node cannot exist in API format.
3. Upload with `save_workflow(workflow_path=...)` (inline, so it shows in the UI).
4. Document it: what it does, every exposed input (cover, audio chunk, prompt, seed, length, size, guide image),
   what it was proven on (job id, GPU seconds, cost: **none yet**), and what it supersedes (nothing).
5. Register it in `secret-lab-widgets/cloud-workflows.json` and the cloud workflow registry with the measured cost.
6. Status ladder: `candidate`, then `chosen`, then `approved`. New version = new `vNNN`; never delete.

The graph to save is `genkwando_engine/graphs/h3_ref2va_window.template.json` (window 0 form). The window > 0 form
adds one LoadImage node (`20`) for the previous take's last frame and points AddGuide's `image` at it.
