"""Doar logo-ul, pe un set: python eval/logo_only.py clips|holdout|final [scări, ex. 360,160]"""
import glob, json, os, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
from core import media, logo as L
from core.check import LOGO_STEP, LOGO_MAX_SIDE
sub = sys.argv[1]
scales = [int(x) for x in sys.argv[2].split(",")] if len(sys.argv) > 2 else None
model = L.load_logo(os.path.join(HERE, "data", "logo_brisa.png"), **({"scales": scales} if scales else {}))
det = L.LogoDetector(model)
tp = fp = fn = ok = n = 0; t0 = time.time(); errs = []
for jf in sorted(glob.glob(os.path.join(HERE, "data", sub, "*.json"))):
    tr = json.load(open(jf, encoding="utf-8"))
    S = [{"t": t, **det.detect(f)} for t, f in media.sample_frames(jf[:-5] + ".mp4", LOGO_STEP, LOGO_MAX_SIDE)]
    iv = [[i["t0"], i["t1"]] for i in L.to_intervals(S, LOGO_STEP)]
    secs = sum(b - a for a, b in iv)
    t = 0.0
    while t < tr["duration"]:
        a = any(x <= t < y for x, y in tr["logo_intervals"]); b = any(x <= t < y for x, y in iv)
        tp += a and b; fp += b and not a; fn += a and not b; t += LOGO_STEP
    ok += (secs >= 3) == (tr["logo_seconds"] >= 3); n += 1; errs.append(abs(secs - tr["logo_seconds"]))
print(f"{sub} scales={scales}: verdict logo {ok}/{n}, precizie {tp/max(1,tp+fp):.3f}, recall {tp/max(1,tp+fn):.3f}, eroare medie {sum(errs)/n:.2f}s, {time.time()-t0:.0f}s")
