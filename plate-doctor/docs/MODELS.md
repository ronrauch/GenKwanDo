# Models and nodes

REMOVE (all open weights):
- `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` (checkpoints/diffusion_models)
- `ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors` (loras)
- `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` (text encoders)
- `ltx-2.5-video-vae-bf16.safetensors`, `ltx-2.5-audio-vae-bf16.safetensors` (vae)

RECOVER, local graph (open weights):
- `ltx-2.3-22b-dev.safetensors`, `ltx-2.3-22b-distilled-lora-384-1.1.safetensors`
- `ltx-2.3-22b-ic-lora-hdr-0.9.safetensors` from Lightricks/LTX-2.3-22b-IC-LoRA-HDR
- a Gemma 3 12B text encoder (`comfy_gemma_3_12B_it.safetensors`)
- custom node pack ComfyUI_essentials (the `SimpleMath+` node in the upstream flow)
- set `OPENCV_IO_ENABLE_OPENEXR=1` before launching ComfyUI or EXR saving fails

Int8-convrot and fp8 kernels are CUDA-first: plan on an NVIDIA GPU or Comfy Cloud, not Apple silicon.
Check each model's own license before use.
