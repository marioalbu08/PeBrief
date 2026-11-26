"""Cât de des are dreptate verdictul, pe setul cu adevăr cunoscut.

Rulare:  python eval/run_eval.py            (fără indiciu de vocabular; implicit)
         python eval/run_eval.py --hint   (cu indiciu, pentru comparație)
Scrie eval/results[-nohint].json și afișează un rezumat.
"""
from __future__ import annotations

import glob
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from core.check import LOGO_STEP, run_check  # noqa: E402
from core.textmatch import norm  # noqa: E402

DATA = os.path.join(HERE, "data")


def inside(t, ivs):
    return any(a <= t < b for a, b in ivs)


def expected(truth, rules):
    exp = {}
    exp["duration"] = rules["min_duration_s"] - 0.25 <= truth["duration"] <= rules["max_duration_s"] + 0.25
    exp["logo"] = truth["logo_seconds"] >= rules["logo_min_seconds"]
    for ph in rules["must_say"]:
        exp["say:" + ph] = ph in truth["said"]
    for ph in rules["must_not_say"]:
        exp["nosay:" + ph] = ph not in truth["forbidden"]
    cap = norm(truth["caption"]).split()
    for it in rules["caption_must_include"]:
        exp["caption:" + it] = norm(it) in cap
    return exp


def got(verdict, rules):
    out = {}
    say = iter(rules["must_say"])
    nosay = iter(rules["must_not_say"])
    capi = iter(rules["caption_must_include"])
    for c in verdict["checks"]:
        key = {"duration": lambda: "duration", "logo": lambda: "logo",
               "say": lambda: "say:" + next(say), "nosay": lambda: "nosay:" + next(nosay),
               "caption": lambda: "caption:" + next(capi)}.get(c["id"])
        if key:
            out[key()] = c["pass"]
    return out


def main():
    hint = "--hint" in sys.argv
    rules = json.load(open(os.path.join(DATA, "rules.json"), encoding="utf-8"))
    logo = os.path.join(DATA, "logo_brisa.png")
    rows = []
    sub = "final" if "--final" in sys.argv else "holdout" if "--holdout" in sys.argv else "clips"
    for jf in sorted(glob.glob(os.path.join(DATA, sub, "*.json"))):
        truth = json.load(open(jf, encoding="utf-8"))
        video = jf[:-5] + ".mp4"
        t0 = time.time()
        v = run_check(video, rules, truth["caption"], logo, use_hint=hint)
        el = time.time() - t0
        exp, g = expected(truth, rules), got(v, rules)
        # logo la nivel de cadru eșantionat
        pred_ivs = [[iv["t0"], iv["t1"]] for iv in v["timeline"]["logo"]]
        tp = fp = fn = tn = dec_fp = dec_n = 0
        t = 0.0
        while t < truth["duration"]:
            a, b = inside(t, truth["logo_intervals"]), inside(t, pred_ivs)
            tp += a and b
            fp += (not a) and b
            fn += a and not b
            tn += (not a) and (not b)
            if inside(t, truth["decoy_intervals"]) and not a:
                dec_n += 1
                dec_fp += b
            t += LOGO_STEP
        pred_secs = next((c.get("value", 0) for c in v["checks"] if c["id"] == "logo"), 0)
        row = {"id": truth["id"], "exp": exp, "got": g, "seconds": round(el, 2),
               "duration": truth["duration"], "logo_true": truth["logo_seconds"], "logo_pred": pred_secs,
               "tp": tp, "fp": fp, "fn": fn, "tn": tn, "decoy_fp": dec_fp, "decoy_n": dec_n,
               "scale": truth["logo_scale"], "blur": truth["blur"], "persp": truth["persp"],
               "say_kind": truth["say_kind"], "transcript": v["transcript"],
               "verdict_ok": all(exp[k] == g.get(k) for k in exp),
               "exp_pass": all(exp.values()), "got_pass": v["pass"]}
        rows.append(row)
        wrong = [k for k in exp if exp[k] != g.get(k)]
        print(f"{truth['id']}  {el:5.1f}s  logo {truth['logo_seconds']:.2f}→{pred_secs:.2f}  "
              f"{'OK ' if not wrong else 'GREȘIT ' + ','.join(wrong)}", flush=True)

    out = os.path.join(HERE, ("results-hint" if hint else "results") + ("" if sub == "clips" else "-" + sub) + ".json")
    json.dump(rows, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    summarize(rows)


def summarize(rows):
    keys = sorted({k for r in rows for k in r["exp"]})
    print("\nAcord pe fiecare verificare (verdict sistem == adevăr):")
    for k in keys:
        rs = [r for r in rows if k in r["exp"]]
        ok = sum(r["exp"][k] == r["got"].get(k) for r in rs)
        fpass = sum(r["exp"][k] is False and r["got"].get(k) is True for r in rs)
        ffail = sum(r["exp"][k] is True and r["got"].get(k) is False for r in rs)
        print(f"  {k:22s} {ok}/{len(rs)}   trecut greșit: {fpass}   picat greșit: {ffail}")
    tp = sum(r["tp"] for r in rows)
    fp = sum(r["fp"] for r in rows)
    fn = sum(r["fn"] for r in rows)
    print(f"\nLogo pe cadre: precizie {tp / max(1, tp + fp):.3f}, recall {tp / max(1, tp + fn):.3f}")
    err = [abs(r["logo_pred"] - r["logo_true"]) for r in rows]
    print(f"Eroare secunde logo: medie {statistics.mean(err):.2f} s, mediană {statistics.median(err):.2f} s, max {max(err):.2f} s")
    dn = sum(r["decoy_n"] for r in rows)
    print(f"Logo-capcană numărat greșit: {sum(r['decoy_fp'] for r in rows)}/{dn} cadre")
    va = sum(r["verdict_ok"] for r in rows)
    print(f"Verdict complet corect (toate verificările): {va}/{len(rows)}")
    fa = sum(r["got_pass"] and not r["exp_pass"] for r in rows)
    print(f"Clipuri aprobate deși nu trebuiau: {fa};  respinse deși erau bune: {sum(r['exp_pass'] and not r['got_pass'] for r in rows)}")
    secs = [r["seconds"] / r["duration"] for r in rows]
    print(f"Timp: {statistics.mean([r['seconds'] for r in rows]):.1f} s pe clip ({statistics.mean(secs):.2f} s per secundă de video)")


if __name__ == "__main__":
    main()
