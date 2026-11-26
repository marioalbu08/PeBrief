"""Distribuția NCC pentru detecțiile adevărate și false, pe setul de reglaj."""
import glob, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
from core import media, logo as L
from core.check import LOGO_STEP, LOGO_MAX_SIDE
sub = sys.argv[1] if len(sys.argv) > 1 else "clips"
det = L.LogoDetector(L.load_logo(os.path.join(HERE, "data", "logo_brisa.png")))
T, F = [], []
for jf in sorted(glob.glob(os.path.join(HERE, "data", sub, "*.json"))):
    tr = json.load(open(jf, encoding="utf-8"))
    for t, f in media.sample_frames(jf[:-5] + ".mp4", LOGO_STEP, LOGO_MAX_SIDE):
        r = det.detect(f)
        if "ncc" in r:
            (T if any(a - 0.05 <= t < b + 0.05 for a, b in tr["logo_intervals"]) else F).append(r["ncc"])
import numpy as np
T, F = np.array(T), np.array(F)
print(f"adevărate n={len(T)}  percentile 1/5/10/50: {np.percentile(T,[1,5,10,50]).round(3)}")
print(f"false     n={len(F)}  max/95/50: {F.max() if len(F) else 0:.3f} {np.percentile(F,95) if len(F) else 0:.3f} {np.median(F) if len(F) else 0:.3f}")
for th in (0.2, 0.3, 0.4, 0.5):
    print(f"prag {th}: păstrează {(T>=th).mean():.3f} din adevărate, {(F>=th).sum()} false din {len(F)}")
