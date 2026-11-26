"""Verdictul: clipul + descrierea, verificate față de reguli, cu dovezi la secundă."""
from __future__ import annotations

import os
import time

import cv2

from . import media, speech
from .logo import LogoDetector, load_logo, to_intervals
from .textmatch import caption_has, find_all, find_phrase

LOGO_STEP = 0.25  # secunde între cadrele verificate
LOGO_MAX_SIDE = 1024  # la 720 px logo-urile mici se pierd (măsurat: eval/REZULTATE.md)


def fmt(t: float) -> str:
    t = max(0.0, t)
    return f"{int(t // 60)}:{t % 60:04.1f}"


def run_check(video: str, rules: dict, caption: str = "", logo_path: str | None = None,
              frames_dir: str | None = None, progress=lambda p, msg: None,
              use_hint: bool = False) -> dict:
    t_start = time.time()
    info = media.probe(video)
    dur = info["duration"]
    checks: list[dict] = []
    timeline: dict = {"duration": dur, "logo": [], "said": [], "forbidden": []}
    evidence_times: set[float] = set()

    # ---- durata
    lo, hi = rules.get("min_duration_s"), rules.get("max_duration_s")
    if lo is not None or hi is not None:
        ok = (lo is None or dur >= lo - 0.25) and (hi is None or dur <= hi + 0.25)
        want = f"{lo:g}–{hi:g} s" if lo is not None and hi is not None else (
            f"minim {lo:g} s" if lo is not None else f"maxim {hi:g} s")
        checks.append({"id": "duration", "label": f"Durată {want}", "pass": ok,
                       "detail": f"Clipul are {dur:.1f} s." + ("" if ok else f" Cerința: {want}."),
                       "evidence": []})

    # ---- logo
    logo_secs = None
    if logo_path and rules.get("logo_min_seconds"):
        progress(0.05, "Caut logo-ul cadru cu cadru")
        det = LogoDetector(load_logo(logo_path))
        samples = []
        n_est = max(1, int(dur / LOGO_STEP))
        for i, (t, frame) in enumerate(media.sample_frames(video, LOGO_STEP, LOGO_MAX_SIDE)):
            r = det.detect(frame)
            samples.append({"t": round(t, 3), **r})
            if i % 8 == 0:
                progress(0.05 + 0.45 * min(1, i / n_est), "Caut logo-ul cadru cu cadru")
        intervals = to_intervals(samples, LOGO_STEP)
        logo_secs = sum(iv["t1"] - iv["t0"] for iv in intervals)
        need = rules["logo_min_seconds"]
        ok = logo_secs >= need - 1e-6
        timeline["logo"] = intervals
        timeline["logo_samples"] = [{"t": s["t"], "q": s["quad"]} for s in samples if s["found"]]
        ev = [{"t": iv["best_t"], "t0": iv["t0"], "t1": iv["t1"],
               "text": f"logo vizibil {fmt(iv['t0'])}–{fmt(iv['t1'])}"} for iv in intervals]
        evidence_times.update(e["t"] for e in ev)
        if intervals:
            detail = (f"Logo-ul se vede {logo_secs:.1f} s din {need:g} s cerute, în "
                      + ", ".join(f"{fmt(iv['t0'])}–{fmt(iv['t1'])}" for iv in intervals) + ".")
        else:
            detail = f"Logo-ul nu apare deloc în clip. Cerința: {need:g} s."
        if not ok and intervals:
            detail += f" Mai trebuie {need - logo_secs:.1f} s: ține produsul cu logo-ul spre cameră mai mult."
        checks.append({"id": "logo", "label": f"Logo vizibil minim {need:g} s", "pass": ok,
                       "detail": detail, "evidence": ev, "value": round(logo_secs, 2)})

    # ---- vorbirea
    must, banned = rules.get("must_say", []), rules.get("must_not_say", [])
    transcript = None
    if must or banned:
        progress(0.55, "Ascult ce se spune")
        wav = media.extract_audio(video)
        if wav is None:
            words = []
            transcript = {"text": "", "words": []}
        else:
            hint = (", ".join(must + [rules.get("brand", "")]) + ".") if use_hint and must else None
            try:
                transcript = speech.transcribe(wav, rules.get("language", "ro"), hint)
            finally:
                os.unlink(wav)
            words = transcript["words"]
        progress(0.9, "Compar cu brief-ul")
        for ph in must:
            m = find_phrase(words, ph)
            if m["status"] == "ok":
                checks.append({"id": "say", "label": f"Spune „{ph}”", "pass": True,
                               "detail": f"Spus la {fmt(m['start'])}: „{m['heard']}”.",
                               "evidence": [{"t": m["start"], "t0": m["start"], "t1": m["end"],
                                             "text": f"„{m['heard']}”"}]})
                timeline["said"].append({"t0": m["start"], "t1": m["end"], "text": ph})
                evidence_times.add(m["start"])
            elif m["status"] == "partial":
                checks.append({"id": "say", "label": f"Spune „{ph}”", "pass": False,
                               "detail": f"La {fmt(m['start'])} ai spus „{m['heard']}”, dar brief-ul cere exact „{ph}”.",
                               "evidence": [{"t": m["start"], "t0": m["start"], "t1": m["end"],
                                             "text": f"„{m['heard']}”"}]})
                timeline["said"].append({"t0": m["start"], "t1": m["end"], "text": m["heard"], "partial": True})
                evidence_times.add(m["start"])
            else:
                checks.append({"id": "say", "label": f"Spune „{ph}”", "pass": False,
                               "detail": f"„{ph}” nu apare în ce se aude în clip.", "evidence": []})
        for ph in banned:
            hits = find_all(words, ph)
            ok = not hits
            ev = [{"t": h["start"], "t0": h["start"], "t1": h["end"], "text": f"„{h['heard']}”"} for h in hits]
            for h in hits:
                timeline["forbidden"].append({"t0": h["start"], "t1": h["end"], "text": h["heard"]})
                evidence_times.add(h["start"])
            checks.append({"id": "nosay", "label": f"Nu spune „{ph}”", "pass": ok,
                           "detail": "Nu apare." if ok else "Apare la " + ", ".join(
                               f"{fmt(h['start'])} („{h['heard']}”)" for h in hits) + ".",
                           "evidence": ev})

    # ---- descrierea
    for item in rules.get("caption_must_include", []):
        ok = caption_has(caption, item)
        checks.append({"id": "caption", "label": f"Descrierea conține {item}", "pass": ok,
                       "detail": "Da." if ok else f"Lipsește {item} din descriere.", "evidence": []})
    for item in rules.get("caption_must_not_include", []):
        ok = not caption_has(caption, item)
        checks.append({"id": "caption_no", "label": f"Descrierea nu conține {item}", "pass": ok,
                       "detail": "Nu apare." if ok else f"Scoate {item} din descriere.", "evidence": []})

    # ---- cadrele-dovadă
    if frames_dir:
        os.makedirs(frames_dir, exist_ok=True)
        for t in sorted(evidence_times):
            f = media.frame_at(video, t)
            if f is not None:
                cv2.imwrite(os.path.join(frames_dir, f"t{int(round(t * 1000))}.jpg"), f,
                            [cv2.IMWRITE_JPEG_QUALITY, 82])

    progress(1.0, "Gata")
    return {
        "pass": all(c["pass"] for c in checks) if checks else False,
        "checks": checks,
        "manual": rules.get("manual", []),
        "timeline": timeline,
        "transcript": transcript["text"] if transcript else None,
        "words": transcript["words"] if transcript else [],
        "video": {k: info[k] for k in ("duration", "width", "height", "fps")},
        "seconds": round(time.time() - t_start, 2),
    }
