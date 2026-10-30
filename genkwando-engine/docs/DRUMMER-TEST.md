# Day-1 test: can H3 land a drummer's sticks on the beat?

Everything about instruments hangs on this. Our rule says an audio model moves a face, never sticks or hands; this
test finds out whether H3's reference-to-video does better than that rule predicts.

1. Take a clean image of one drummer, square, hands and sticks in frame, and a song with a clear drum part.
2. Note the tempo (bpm) and the time of the first beat in the slice.
3. Dry run first (free): `python3 -m genkwando_engine drummer-test --cover drummer.png --song song.wav --bpm 120`
   prints the plan and writes the graph and audio chunk. Look at `takes/drummer/w0/t001.graph.json`.
4. One live window (spends credits; needs `--go` and a key): add `--go --first-beat 0.25`.
5. The command burns a red box in the corner of the take that flashes on every beat. Watch the take against it.

Judge honestly, three questions:
- Do the sticks hit on the flashes, or only move about at the right speed?
- Do hands and sticks keep their shape for the whole window?
- Does it hold for a second window chained from the first?

Record the result (take id, seed, cost) here. **Until a take passes, instruments stay labelled UNPROVEN and the
performance-capture lane is the fallback.** Do not tick this off from a still frame.

Result: _not run yet_.
