# Saving the graphs to Comfy (NOT done yet)

Authorship rule for every workflow we build: it is saved into Comfy (inline, so it shows on the canvas), named,
documented, and registered. None of that has happened for Plate Doctor. Do it when the graphs are proven on a real run.

| Graph | Save as | Source in this repo |
|---|---|---|
| REMOVE | `SECRETLAB-LTX25-PlateDoctor-v001` | `graphs/ltx25-cleanplate.api.json` |
| RECOVER | not saved | derived from Lightricks' workflow under the LTX-2 Community License: check those terms before saving a derivative anywhere |

Steps (later, via the lab's `secretlab_save.py`, then `save_workflow(workflow_path=...)`):
1. Build save-format JSON from the API graph with both documentation notes on the canvas. Saving an API graph inline
   silently drops notes (MarkdownNote is frontend-only).
2. Notes say: what it does, every exposed input (nodes 10, 20, 23, 40, 51, 62), what it was proven on (job id,
   gpu-seconds, cost), what it supersedes (the project-specific clean-plate graphs).
3. Status ladder: `candidate` first. Never "FINAL".
4. Register it in the lab's cloud-workflows registry with MEASURED cost.
