# Models and nodes

REMOVE (all open weights):
- `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` (checkpoints/diffusion_models)
- `ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors` (loras)
- `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` (text encoders)
- `ltx-2.5-video-vae-bf16.safetensors`, `ltx-2.5-audio-vae-bf16.safetensors` (vae)

RECOVER, local graph:
- `ltx-2.3-22b-dev.safetensors`, `ltx-2.3-22b-distilled-lora-384-1.1.safetensors`
- `ltx-2.3-22b-ic-lora-hdr-0.9.safetensors` from Lightricks/LTX-2.3-22b-IC-LoRA-HDR
- a Gemma 3 12B text encoder (`comfy_gemma_3_12B_it.safetensors`)
- the workflow itself is NOT in this repo: download `LTX-2.3_ICLoRA_HDR_Distilled.json` from the LTX-2.3 example
  workflows in https://github.com/Lightricks/ComfyUI-LTXVideo, then `python3 -m plate_doctor fetch-graph --from <file>`
- custom nodes that workflow may need (for example ComfyUI_essentials' `SimpleMath+`); check the file you downloaded
- set `OPENCV_IO_ENABLE_OPENEXR=1` before launching ComfyUI or EXR saving fails

Int8-convrot and fp8 kernels are CUDA-first: plan on an NVIDIA GPU or Comfy Cloud, not Apple silicon.
**Licence:** using LTX models, the in/outpainting and HDR IC-LoRAs and Lightricks' workflows is governed by the
LTX-2 Community License Agreement (https://github.com/Lightricks/ComfyUI-LTXVideo). Read it yourself; this repo does not
summarize its terms. Our REMOVE graph (`graphs/ltx25-cleanplate.api.json`) is an original Secret Lab recipe, not a
vendor example; it only *loads* the models above.
