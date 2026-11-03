# GenKwanDo EASY v1 — notes (2026-11-03)

Cloud record: **GenKwanDo/EASY-v1**, workflow_id `a49d4504-00ce-450d-b495-56428c851dd9` (new record, v1). Not shared, no app, no app link. MASTER v4 (`1909b6af…`) and "GenKwanDo App.app" (`db7b3fcc…`) were not touched.
Files here: `genkwando-easy-v1.api.json` (API format, 160 nodes), `EASY-v1-four-man-band-30s.mp4`, `EASY-v1-logs/` (every auto-written prompt and instrument list).
The UI-format version exists only as the Cloud record above (the server converted the API graph on save). I did not export a local UI JSON.

## What the user touches
1. **Node 6, LoadImage:** one image, any size.
2. **Node 7, LoadAudio:** one song, the full mix.
3. Optional widgets:
   - node 18 `keep_proportion` (`crop` = centre crop, the default; `pad` = keep the whole image with black bars);
   - node 8 `start_index` (start offset in seconds).

That's all. Then press Run.

## What the graph does (zones)
- **Z1 square.** `ImageResizeKJv2` brings the image to 1248×1248 /32 with lanczos, which upscales small images. Tested on Cloud on a 320×180 and a 200×200 thumbnail made from the cover: crop and pad both gave 1248×1248, and pad gave black bars (top rows mean luma 0.0).
  - The upscale is lanczos only, with no model upscaler.
- **Z1 trim.** `TrimAudioDuration` takes start_index (the offset) and 30.2917 s, which is 727 frames. Every slice and the final mux come from this trimmed song.
- **Z3 stems.** `AudioStemSeparate` with **htdemucs** (4 stems). Output order was measured against v4's stems: out0 vocals, out1 bass, out2 drums, out3 other (correlation 0.947 / 0.983 / 0.989 / 0.796).
  - Vocals (out0) and drums (out2) feed the same H3 `ref_audio_0/1` slices v4 used (nodes 110/111/210/211/310/311).
  - I rejected htdemucs_6s: its "other" stem on the country song is 5.9 dB quieter (-24.6 vs -18.7 dBFS), because its guitar and piano outputs are dropped.
- **Z3 instrument ID (Ron's request).**
  - `GeminiNodeV3` (Gemini 3.1 Pro, temperature 0.2, seed 42) listens to the trimmed song and, separately, to the "other" stem. It returns a fixed format: `SOURCE | WHEN (s) | CONFIDENCE`.
  - Cross-check: `AudioLoudnessMeter` (open source, ComfyUI_AudioTools) gives LUFS per stem per 10.125 s window, 12 numbers.
  - Both lists and the LUFS table go to the auto-prompt, with the rule "heard = named by Gemini (family match) AND stem louder than about -40 LUFS".
- **Z2 auto-prompt.**
  - A second `GeminiNodeV3` call sees the squared cover, the instrument lists and the loudness table. It fills 13 tagged slots and does not write the prompt itself.
  - The slots are MOOD, STYLE, SHOT, PALETTE, SUBJECTS, WORLD_MOTION, SINGER_LINE, PLAYERS, WORLD_ANSWER, SOUNDSCAPE, MUSIC, INSTRUMENTS and HEARD_NO_PLAYER.
  - `RegexReplace` pulls each slot out, and `StringReplace` drops it into a **fixed template built from v4's prompt structure** (subject_definitions / summary / retention_analysis / detailed_description / overall_soundscape / non_diegetic_music). The per-window PICLINE and ARC lines are fixed text from v4.
  - Rules given to the model:
    - exactly one singer or none: a person at a microphone; with no microphone, a lone performer with a free mouth; a group with no microphone gets none;
    - never invent people or instruments;
    - a player whose instrument is heard plays its sound;
    - a player whose instrument is unheard moves to the beat only;
    - a heard instrument with no player is listed as "(heard, no player on the cover)" and never given to a person;
    - match by instrument family (horns, guitars, keys, bowed strings, basses);
    - zero negation words.
  - Safety net: a regex drops any clause that holds no/not/never/nothing/without/none/nor/neither/nobody/cannot/…n't, then tidies the punctuation.
- **User-facing text outputs:**
  - Four `PreviewAny` boxes: instruments heard (with times); heard vs cover (who plays what, who moves to the beat); "heard, no player on the cover"; stem loudness.
  - `SaveText` files for the same, plus the raw LLM text and the three window prompts.
- **Z5/Z7: exactly v4.** 3×243 windows with last-frame guides; turbo 4-step LoRA; res_multistep + kl_optimal at 8 steps; seed 210664234423221 on all three windows; same UNET, CLIP, VAEs, sizes and assembly (243+242+242 = 727 frames, 24 fps, original mix).
- **Z8 colour match (optional extra output, NOT proven in a full run).** `ColorMatchV2` reinhard at strength 0.5, run **per window** (243/242/242 frames), then concat, saved as `…-30s-colourmatch`. The plain v4-style output (node 922) is still saved alongside.

## Run 1 — four-man band + song-anthem (render 1 of 3, prompt_id df19da74-ac0c-4e6d-89b4-6bfbd61a05a8)
**Auto-written prompt:** `EASY-v1-logs/four-man-band-prompt-w{1,2,3}.txt`.
- Negation words in the final W1/W2/W3 prompts: **0 / 0 / 0**. No `{SLOT}` left unfilled.
- The raw LLM text holds 4 "no", all inside "(heard, no player on the cover)" in the INSTRUMENTS and HEARD_NO_PLAYER slots. Those slots never enter the H3 prompt.

**People and instruments:**
- SUBJECTS lists 4 people (bassist, singer, trumpeter, drummer) plus the world. That matches the cover, and nobody is invented.
- Match output:
  - singer → vocals; drummer → drums; bassist → bass;
  - **trumpeter → the horn line**: Gemini called it "saxophone", and the family rule mapped it to the trumpeter;
  - "electric guitar, synthesizer (heard, no player on the cover)".

**Scores, same judge chain as v4** (jim2band/tools/judge.sh, stems30, band4 boxes, cover in/cover.png). "v4" is the original 1248 v4 render (JIM2-S221 = MASTER-v4-band-30s.mp4); the examples copy `band-30s-v4.mp4` (720×720) was re-judged today as a check.

| measure | EASY v1 | v4 (1248) | v4 examples copy (720) |
|---|---|---|---|
| file | 1248², 727 f, 30.290 s, audio | same | 720², 727 f |
| frame 0 vs cover (ZNCC) | 0.9944 | 0.9952 | 0.9932 |
| joins 242/243, 484/485 | 0.984 / 0.9888 | 0.987 / 0.9885 | 0.9892 / 0.9907 |
| scene hold ZNCC min | 0.756 @373 | 0.848 @379 | 0.853 @380 |
| brightness drift (luma dev max) | **49.4%** | 39.7% | 39.9% |
| lips Pearson / closed / phrase | **0.531** / 0.789 / 12.5% | 0.484 / 0.752 / 12.5% | 0.478 / 0.745 / 12.5% |
| bassist lock p | 0.055 | 0.058 | 0.040 |
| drummer lock p | 0.018 | 0.013 | 0.020 |
| trumpeter lock p | 0.555 | 0.435 | 0.499 |
| separation (pair corr max) | 0.556 | 0.572 | 0.571 |
| world r | 0.099 | 0.119 | 0.108 |
| face stability | 0.141 | 0.163 | 0.171 |
| YDIF mean / max (frame) | 1.716 / 5.11 (252) | 1.585 / 4.63 (653) | 1.463 / 4.46 (653) |
| frames > 3× mean YDIF | 0 | 0 | 1 |
| region YDIF mean: bass / drum / trumpet / singer | 3.98 / 2.15 / 3.62 / 2.46 | 3.48 / 2.27 / 3.98 / 2.38 | — |

**Reading:**
- With no hand-written prompt and no pre-split stems, EASY v1 keeps v4's two locks: bassist p 0.055 and drummer p 0.018, both under 0.10.
- Lips are better: Pearson 0.531 vs 0.484.
- Joins and frame 0 are within ±0.003.
- It is worse on brightness drift (49.4% vs 39.7%) and scene hold (0.756 vs 0.848).
- The trumpeter is still unlocked (0.555 vs 0.435).
- The gate verdict is the same as v4: FAIL on 5 lines (scene hold, lips, players, world, face).

**Colour match measured locally (not in-graph).** I applied `tools/colour_match.py` (per-frame mean/std match, strength 0.5) to Run 1 and re-scored it:
- brightness drift 49.4% → 25.7%;
- bassist p 0.054, drummer p 0.016;
- world r 0.171;
- joins 0.985 / 0.990.

That file stays in scratch (`easy-v1/cm/`); it is not a deliverable.

## Run 2 — unseen cover: FAILED TO RUN
- The plan was cover-porch-guitarist.jpg + song-porch-country.mp3, run from the saved EASY-v1 record. That would also have been the first in-graph test of the Z8 colour match.
- Cloud answered **"workspace is out of credits"** (`insufficient_credits`). No job was created and nothing was spent. Per the tool's instruction I did not retry.
- **There is no `EASY-v1-porch-30s.mp4`.** Only 1 of the 3 allowed renders was used.
- What *is* shown for the unseen cover is the text path only: the auto-prompt and instrument ID ran on Cloud in the analysis test job a0ae0386 (porch + country song, below). That ran before the rule fixes.

## Instrument ID — what Gemini named vs what is in the song
**song-anthem** (the band is singer, bass, trumpet, drums):
- **Named in the mix:** drum kit 0-30, electric bass 0-30, electric guitar 0-30, synth 0-8 and 15-30, lead vocals 8-25.
- **Named in the other stem:** saxophone, electric guitar, synthesizer.
- **Hits:** vocals, bass, drums.
- **Miss:** the trumpet is never named. It was called "saxophone" in the other stem; the family rule recovers it.
- **False hits against the stated line-up:** electric guitar and synth. Both reach only the MUSIC line and the "no player" list, never a person.
- **Vocal timing:** Gemini gives 8-25 s; the measured phrases run 8.7-28.15 s, so the short tail phrases (25.75-28.15 s) are missed.
- **Loudness cross-check:** all four stems are louder than -21 LUFS in every window.
  - The integrated-LUFS gate ignores silence, so a stem with one phrase in a window reads loud. It catches silent windows only, not sparse ones.

**song-porch-country** (no instrumentation tags were recorded at generation, so ground truth is the stems only):
- **Named in the mix:** acoustic guitar 0-30, lead vocals 4-17, upright bass 4-30, drum kit 7-30, electric guitar 10-30, violin 14-30.
- **Named in the other stem:** acoustic guitar, synthesizer 4-30, fiddle 14-30.
- **Checked against the stems:**
  - vocals: stem active in windows 1-2 and silent in window 3 (-55 LUFS); measured phrases 3.5-20.05 s. Gemini's 4-17 is right in shape and ends about 3 s early.
  - **bass: the stem is silent in window 1 (-52 LUFS, -69 dBFS)**, so Gemini's "4-30" is a false start for 4-10 s. The loudness table catches this.
  - drums: active in window 1 (-17.6 LUFS); "7-30" is consistent.
  - violin, electric guitar, synth: all sit in "other", which is active in every window. They cannot be verified with 4 stems; treat them as unverified.

**Determinism:** the anthem instrument list from Run 1 is byte-identical to the analysis job's list (same file hash), so the same input gives the same list.

## Auto-prompt method: measured obedience (text only, Cloud job a0ae0386, 6 covers, before the rule fixes)

| cover (song) | people named / actually visible | invented people or instruments | singer chosen | negation words in slots |
|---|---|---|---|---|
| four-man band (anthem) | 4 / 4 | 0 | the man at the mic | 0 |
| soul singer (anthem) | 1 / 1 | 0; drums, bass, guitar, synth, sax all listed as "heard, no player" | the man at the mic | 0 |
| big band (anthem) | 3 (sax, singer, bassist) / 7 in the full 16:9 cover | 0 | singer at mic | 0 |
| garage trio (anthem) | 3 / 3 | 0 | centre guitarist (no mic) | 0 |
| porch guitarist (country) | 1 / 1 | 0 | the guitarist (lone performer) | 0 |
| string quartet (country) | 4 / 4 | 0 | **a violinist (wrong)** | 0 |

**Notes on this table:**
- **Big band:** the centre crop to a square drops the sides of the 16:9 cover. I did not count how many people survive the crop. Pad mode keeps them all.
- **Fixes after this test:**
  - the trumpet → sax confusion was fixed with family matching, and Run 1 confirms the trumpeter now gets the horn line;
  - the "group with no mic → no singer" rule was added for garage and quartet. That rule was **not re-tested**, because the account ran out of credits.
- **Negation:** across 7 real Gemini outputs (6 test + Run 1), the LLM slot text held **0 negation words**, and the regex cleanup never had to fire.
- **Cleanup on a synthetic sentence:** it removes the negated clauses but leaves a stray ". ," in the text, a cosmetic flaw.
- **LLM vs generic template:**
  - I did not render the positive generic template, so there is no video comparison.
  - On text, the LLM obeyed the negation rule 7/7 and invented 0 people.
  - The generic template cannot name players or map stems, so the LLM path is the default.
  - If Gemini returns malformed tags, the slot regex passes the whole raw text through. There is no automatic fallback to the generic template.

## Colour match (nice to have)
- **ColorMatchV2, GPU (`reinhard_lab_gpu`), 727 frames at 1248, no H3 in the job:** **out of GPU memory** (torch OOM; job 3d6c3c66).
- **Per window, 243 frames:** both `reinhard` (CPU, multithread) and `reinhard_lab_gpu` **ran** (job a8c47eaa, no H3 in the job).
- **In the workflow:** the CPU per-window version is wired as optional output Z8.
  - Risk: it was never run inside a full H3 job, because Run 2 was refused for credits.
  - If it crashes the worker the way v5a did, delete nodes 1103-1108; the plain v4 output (922) doesn't depend on them.
- **Expected effect, from the local equivalent on Run 1:** brightness drift 49.4% → 25.7%.

## Paid / not open source
- Instrument ID and the cover reader use **Gemini (GeminiNodeV3)**. It is a paid partner API, not open source.
  - 3 Gemini calls per run; 10 calls in the analysis test.
  - I found no open audio tagger on Cloud (no CLAP / PANNs / AST).
- Open alternative for the cover reader, not tried: core `TextGenerate` with a Qwen-VL CLIP.
- Everything else is open source: Demucs, the loudness meter, the string and regex nodes, MiniMax H3.

## What failed / open items
- **Run 2 (unseen cover) not rendered:** the Cloud workspace is out of credits. Add credits, then run the saved record with these overrides:
  - node 6 image `80555aeff0dbfc601382125deb019fbe215a3cca795e6500aeaf09da4590a952.png`
  - node 7 audio `f0587e83daa1d063f4c63dd5452223d2a9b349bf32d0d9d42c91a109e79c71f2.flac`
  - output prefixes (nodes 108/208/308/922/1002-1005/1094-1102/1108) changed to `…EASY-v1-porch…`
- The singer and family rule changes are tested on one render only (the family rule, Run 1). The group-no-mic rule is untested.
- The Z8 colour match is untested inside a full H3 run.
- Brightness drift is worse than v4 (49.4% vs 39.7%) and the trumpeter is still unlocked (p 0.555).
- The v4 per-window counts ("14 kicks, from 0.02 s") are gone. The template says "on each kick" without numbers, because counting onsets needs tools outside the graph.
- The node-18 crop can cut people off wide covers; switch it to pad for those.
