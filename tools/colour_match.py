# Match every frame's colour to the cover, after rendering.
# usage: python colour_match.py render.mp4 cover.png out.mp4 WINDOW STRENGTH
# The four-man band video used WINDOW 1, STRENGTH 0.5. Mux the song back in with ffmpeg afterwards.
import sys, cv2, numpy as np
src, ref, out, win, strength = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), float(sys.argv[5])
r = cv2.imread(ref).astype(np.float32); rm, rs = r.reshape(-1,3).mean(0), r.reshape(-1,3).std(0)
cap = cv2.VideoCapture(src); fps = cap.get(5); F = []
while True:
    ok, f = cap.read()
    if not ok: break
    F.append(f)
M = np.array([f.reshape(-1,3).mean(0) for f in F]); S = np.array([f.reshape(-1,3).std(0) for f in F])
if win > 1:
    k = np.ones(win)/win; pad = win//2
    sm = lambda a: np.stack([np.convolve(np.pad(a[:,c],(pad,pad),mode='edge'),k,'valid') for c in range(3)],1)
    M, S = sm(M), sm(S)
w = cv2.VideoWriter(out, cv2.VideoWriter_fourcc(*'mp4v'), fps, (F[0].shape[1], F[0].shape[0]))
for f, m, s in zip(F, M, S):
    f = f.astype(np.float32); g = (f - m) / (s + 1e-6) * rs + rm
    w.write(np.clip(f + strength*(g - f), 0, 255).astype(np.uint8))
w.release()
