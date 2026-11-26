"""Setul de test cu adevăr cunoscut.

Pentru fiecare clip știm exact: în ce cadre e logo-ul, ce s-a spus și ce e în
descriere. Fundalurile sunt TikTok-uri reale de creatori (cu vorbire în
engleză pe fundal, deci zgomot realist). Peste ele punem:
  - logo-ul inventat "Brisa Zero", deformat ca un produs ținut în mână
    (perspectivă, rotație, blur, lumină, tremur);
  - uneori un logo-capcană ("VOLTA"), care nu trebuie numărat;
  - voce românească (edge-tts) care spune sau nu frazele din brief.

Rulare:  python eval/make_dataset.py 40
         python eval/make_dataset.py 30 --holdout   (setul nevăzut)
         python eval/make_dataset.py 30 --final     (setul final, rulat o dată)
"""
from __future__ import annotations

import asyncio
import glob
import json
import math
import os
import random
import subprocess
import sys

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from core.media import ffmpeg_exe  # noqa: E402

DATA = os.path.join(HERE, "data")
OUT = os.path.join(DATA, "clips")
FONTS = "C:/Windows/Fonts/"
W, H, FPS = 576, 1024, 30

RULES = {
    "brand": "Brisa Zero", "language": "ro",
    "min_duration_s": 10, "max_duration_s": 30, "logo_min_seconds": 3,
    "must_say": ["Brisa Zero", "fără zahăr"],
    "must_not_say": ["alcool", "Cola", "gratis"],
    "caption_must_include": ["#ad", "#brisazero"],
    "caption_must_not_include": [], "manual": [],
}


# ------------------------------------------------------------------ logos

def make_logo(path, text, sub, c1, c2, font="bahnschrift.ttf", icon="wave"):
    img = Image.new("RGBA", (720, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([4, 4, 716, 296], 48, fill=c1)
    # pictograma
    if icon == "wave":
        d.ellipse([34, 50, 234, 250], fill=c2)
        for k in range(3):
            y = 110 + k * 34
            pts = [(54 + x, y + 14 * math.sin(x / 18 + k)) for x in range(0, 161, 4)]
            d.line(pts, fill=c1, width=10)
    else:
        d.polygon([(134, 40), (234, 150), (164, 150), (194, 260), (44, 120), (114, 120)], fill=c2)
    f1 = ImageFont.truetype(FONTS + font, 108)
    f2 = ImageFont.truetype(FONTS + "arialbd.ttf", 46)
    d.text((262, 52), text, font=f1, fill=c2)
    d.text((268, 186), sub, font=f2, fill=c2)
    img.save(path)


# ------------------------------------------------------------------ audio

SCRIPTS = {
    "both": ["Salut! Azi încerc {brand}, noua băutură {fz}. E răcoritoare și are gust bun.",
             "Bună, oameni buni! Vreau să vă arăt {brand}. Este {fz} și chiar îmi place.",
             "Am descoperit {brand} săptămâna asta. Gust plin, dar {fz}. Mă bucur că l-am găsit."],
    "partial": ["Salut! Azi încerc Brisa, noua băutură {fz}. E răcoritoare și are gust bun.",
                "Bună, oameni buni! Vreau să vă arăt Brisa. Este {fz} și chiar îmi place."],
    "no_fz": ["Salut! Azi încerc {brand}, o băutură nouă. E răcoritoare și are gust bun.",
              "Am descoperit {brand} săptămâna asta. Are un gust plin și e perfectă vara."],
    "none": ["Salut! Azi vă arăt ce beau dimineața. Ceva rece și cu gust bun.",
             "Bună, oameni buni! Am găsit o băutură nouă și vreau să vă spun ce cred."],
}
FORBIDDEN_TAILS = {"alcool": "Și nu are alcool deloc.", "Cola": "E mai bună decât orice Cola.",
                   "gratis": "Azi o primiți gratis la magazin."}
VOICES = ["ro-RO-AlinaNeural", "ro-RO-EmilNeural"]

# Set separat (--holdout): alte propoziții, scrise după ce codul a fost înghețat,
# ca evaluarea să nu fie făcută pe aceleași fraze pe care s-au reglat pragurile.
HOLDOUT_SCRIPTS = {
    "both": ["Pauză de la filmări. Beau o {brand} rece, că e {fz} și nu mă îngreunează.",
             "Ok, recomandarea zilei: {brand}. Știu, sună ciudat, dar e {fz} și are gust de vară.",
             "Dacă vă place ceva dulce dar {fz}, încercați {brand}. Eu o iau mereu la sală."],
    "partial": ["Recomandarea zilei e Brisa. E {fz} și are gust de vară.",
                "Am luat o Zero de la Brisa, e {fz}, chiar e bună."],
    "no_fz": ["Ok, recomandarea zilei: {brand}. Are gust de vară și e super rece.",
              "Pauză de la filmări. Beau o {brand} și mă relaxez puțin."],
    "none": ["Pauză de la filmări. Beau ceva rece și mă relaxez puțin.",
             "Recomandarea zilei e o băutură pe care o iau mereu la sală."],
}
HOLDOUT_TAILS = {"alcool": "Și e fără alcool, deci merge și la volan.", "Cola": "Mult mai bună ca o Coca-Cola.",
                 "gratis": "Primii o sută o primesc gratis."}


async def tts(text, voice, rate, path):
    import edge_tts
    for attempt in range(5):  # serviciul dă uneori NoAudioReceived
        try:
            await edge_tts.Communicate(text, voice, rate=rate).save(path)
            return
        except Exception:  # noqa: BLE001
            if attempt == 4:
                raise
            await asyncio.sleep(1.5 * (attempt + 1))


def audio_dur(path):
    p = subprocess.run([ffmpeg_exe(), "-i", path], capture_output=True, text=True)
    import re
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", p.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])


# ------------------------------------------------------------------ video

def warp_logo(logo_rgba, frame_w, scale, rot, persp, rng):
    lw = int(frame_w * scale)
    lh = int(lw * logo_rgba.shape[0] / logo_rgba.shape[1])
    lg = cv2.resize(logo_rgba, (lw, lh), interpolation=cv2.INTER_AREA)
    src = np.float32([[0, 0], [lw, 0], [lw, lh], [0, lh]])
    jit = rng.uniform(-persp, persp, (4, 2)) * [lw, lh]
    dst = src + jit
    c, s = math.cos(rot), math.sin(rot)
    ctr = dst.mean(0)
    dst = (dst - ctr) @ np.array([[c, -s], [s, c]]).T + ctr
    dst -= dst.min(0)
    M = cv2.getPerspectiveTransform(src, np.float32(dst))
    bw, bh = int(dst[:, 0].max()) + 2, int(dst[:, 1].max()) + 2
    out = cv2.warpPerspective(lg, M, (bw, bh), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
    return out


def composite(frame, sprite, x, y, opacity, blur, gain):
    h, w = sprite.shape[:2]
    if blur > 0:
        sprite = cv2.GaussianBlur(sprite, (0, 0), blur)
    rgb = np.clip(sprite[:, :, :3].astype(np.float32) * gain, 0, 255)
    a = sprite[:, :, 3:4].astype(np.float32) / 255 * opacity
    roi = frame[y:y + h, x:x + w].astype(np.float32)
    frame[y:y + h, x:x + w] = (rgb * a + roi * (1 - a)).astype(np.uint8)


def schedule(rng, dur, total):
    """Unul sau două intervale care însumează `total` secunde."""
    if total <= 0:
        return []
    if total > 2 and rng.random() < 0.4:
        a = rng.uniform(0.35, 0.65) * total
        parts = [a, total - a]
    else:
        parts = [total]
    out, t = [], rng.uniform(0.5, 2.5)
    for p in parts:
        if t + p > dur - 0.3:
            break
        out.append([round(t, 2), round(t + p, 2)])
        t += p + rng.uniform(1.0, 3.0)
    return out


def make_clip(i, rng, bgs, logos):
    cid = f"c{i:03d}"
    # ---- vorbirea
    say = rng.choice(["both"] * 5 + ["partial"] * 2 + ["no_fz"] * 2 + ["none"])
    scripts, tails = (HOLDOUT_SCRIPTS, HOLDOUT_TAILS) if HOLDOUT else (SCRIPTS, FORBIDDEN_TAILS)
    text = rng.choice(scripts[say]).format(brand="Brisa Zero", fz="fără zahăr")
    forb = []
    if rng.random() < 0.3:
        k = rng.choice(list(tails))
        forb = [k]
        text += " " + tails[k]
    voice = rng.choice(VOICES)
    rate = f"{rng.choice([-10, 0, 0, 10, 15]):+d}%"
    mp3 = os.path.join(OUT, cid + ".tts.mp3")
    asyncio.run(tts(text, voice, rate, mp3))
    tdur = audio_dur(mp3)
    t_voice = rng.uniform(0.3, 1.5)
    dur = round(max(rng.uniform(11, 22), t_voice + tdur + 1.0), 2)
    if rng.random() < 0.08:  # câteva clipuri prea scurte
        dur = round(max(t_voice + tdur + 0.3, 8.0), 2)
        if dur >= 10:
            dur = round(t_voice + tdur + 0.3, 2)

    # ---- logo-ul
    total = rng.choice([0.0] + [rng.uniform(1.0, 2.5)] * 2 + [rng.uniform(3.5, 7.0)] * 5)
    ivs = schedule(rng, dur, total)
    decoy_ivs = schedule(rng, dur, rng.uniform(2, 4)) if rng.random() < 0.3 else []
    scale = rng.uniform(0.16, 0.42)
    rot = math.radians(rng.uniform(-22, 22))
    persp = rng.uniform(0.0, 0.14)
    blur = rng.choice([0, 0, 0.6, 1.0, 1.6])
    gain = rng.uniform(0.7, 1.15)
    opacity = rng.uniform(0.9, 1.0)
    sprite = warp_logo(logos["brisa"], W, scale, rot, persp, rng)
    decoy = warp_logo(logos["volta"], W, rng.uniform(0.2, 0.4), math.radians(rng.uniform(-15, 15)), 0.08, rng)
    sh, sw = sprite.shape[:2]
    x0 = int(rng.uniform(0.03, 0.97) * (W - sw))
    y0 = int(rng.uniform(0.35, 0.85) * (H - sh))
    dh, dw = decoy.shape[:2]
    dx0, dy0 = int(rng.uniform(0, 1) * (W - dw)), int(rng.uniform(0.1, 0.4) * (H - dh))

    # ---- fundalul
    bg = rng.choice(bgs)
    cap = cv2.VideoCapture(bg)
    bdur = cap.get(7) / cap.get(5)
    start = rng.uniform(0, max(0, bdur - dur - 0.5))
    cap.set(cv2.CAP_PROP_POS_MSEC, start * 1000)
    n = int(round(dur * FPS))
    silent = os.path.join(OUT, cid + ".v.mp4")
    enc = subprocess.Popen(
        [ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "26", "-pix_fmt", "yuv420p", silent], stdin=subprocess.PIPE)
    vis_frames = 0
    phase = rng.uniform(0, 6.28)
    last = None
    for f in range(n):
        ok, fr = cap.read()
        if not ok:
            fr = last if last is not None else np.zeros((H, W, 3), np.uint8)
        last = fr
        fr = cv2.resize(fr, (W, H))
        t = f / FPS
        if any(a <= t < b for a, b in ivs):
            vis_frames += 1
            jx = int(8 * math.sin(2.1 * t + phase) + rng.uniform(-2, 2))
            jy = int(6 * math.cos(1.7 * t + phase) + rng.uniform(-2, 2))
            x = min(max(0, x0 + jx), W - sw)
            y = min(max(0, y0 + jy), H - sh)
            composite(fr, sprite, x, y, opacity, blur, gain)
        if any(a <= t < b for a, b in decoy_ivs):
            composite(fr, decoy, dx0, dy0, 1.0, 0, 1.0)
        enc.stdin.write(fr.tobytes())
    enc.stdin.close()
    enc.wait()
    cap.release()

    # ---- sunetul: voce + sunetul original al clipului, încet
    final = os.path.join(OUT, cid + ".mp4")
    bgvol = rng.choice([0.08, 0.15, 0.25])
    subprocess.run(
        [ffmpeg_exe(), "-y", "-loglevel", "error", "-i", silent, "-ss", f"{start:.2f}", "-t", f"{dur:.2f}",
         "-i", bg, "-i", mp3, "-filter_complex",
         f"[1:a]volume={bgvol}[b];[2:a]adelay={int(t_voice * 1000)}:all=1[v];"
         f"[b][v]amix=inputs=2:duration=first:normalize=0[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "96k",
         "-t", f"{dur:.2f}", final], check=True)
    os.unlink(silent)
    os.unlink(mp3)

    caption = rng.choice(["Dimineața mea perfectă ☀️", "Ce beau vara asta", "Gust nou!"])
    tags = []
    if rng.random() < 0.8:
        tags.append("#ad")
    if rng.random() < 0.85:
        tags.append("#brisazero")
    caption = caption + " " + " ".join(tags + ["#vara"])
    said = []
    if say in ("both", "no_fz"):
        said.append("Brisa Zero")
    if say in ("both", "partial"):
        said.append("fără zahăr")
    truth = {
        "id": cid, "duration": dur, "logo_intervals": ivs, "logo_seconds": round(vis_frames / FPS, 3),
        "decoy_intervals": decoy_ivs, "said": said, "say_kind": say, "forbidden": forb,
        "caption": caption, "text": text, "voice": voice, "rate": rate, "bg_volume": bgvol,
        "logo_scale": round(scale, 3), "blur": blur, "persp": round(persp, 3),
        "rot_deg": round(math.degrees(rot), 1), "background": os.path.basename(bg),
    }
    with open(os.path.join(OUT, cid + ".json"), "w", encoding="utf-8") as fh:
        json.dump(truth, fh, ensure_ascii=False, indent=1)
    return truth


HOLDOUT = "--holdout" in sys.argv or "--final" in sys.argv
FINAL = "--final" in sys.argv
if HOLDOUT:
    OUT = os.path.join(DATA, "final" if FINAL else "holdout")
if FINAL:
    # Setul final: propoziții scrise după ultima modificare de cod, rulat o singură dată.
    HOLDOUT_SCRIPTS = {
        "both": ["Vă zic sincer, {brand} e singura răcoritoare pe care o beau acum. E {fz}, deci zero vinovăție.",
                 "Am fost la plajă toată ziua și am avut la mine {brand}. Bună, rece și {fz}.",
                 "Întrebarea voastră de ieri: ce beau la birou? Răspuns: {brand}, că e {fz}."],
        "partial": ["Vă zic sincer, Brisa e singura răcoritoare pe care o beau acum. E {fz}.",
                    "Am fost la plajă toată ziua și am avut la mine o Brisa. Bună, rece și {fz}."],
        "no_fz": ["Vă zic sincer, {brand} e singura răcoritoare pe care o beau acum.",
                  "Întrebarea voastră de ieri: ce beau la birou? Răspuns: {brand}, mereu rece."],
        "none": ["Am fost la plajă toată ziua și am avut la mine ceva rece de băut.",
                 "Întrebarea voastră de ieri: ce beau la birou? O să vă zic în clipul următor."],
    }
    HOLDOUT_TAILS = {"alcool": "N-are pic de alcool, deci e ok pentru oricine.",
                     "Cola": "Am renunțat la Cola pentru ea.",
                     "gratis": "Și dacă dați share, poate vă trimit una gratis."}


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    os.makedirs(OUT, exist_ok=True)
    logos = {}
    for key, args in {"brisa": ("Brisa", "ZERO · fără zahăr", (12, 74, 110, 255), (255, 214, 64, 255), "bahnschrift.ttf", "wave"),
                      "volta": ("VOLTA", "energy drink", (24, 24, 24, 255), (120, 255, 90, 255), "impact.ttf", "bolt")}.items():
        p = os.path.join(DATA, f"logo_{key}.png")
        make_logo(p, *args)
        logos[key] = cv2.imread(p, cv2.IMREAD_UNCHANGED)[:, :, [0, 1, 2, 3]]
    with open(os.path.join(DATA, "rules.json"), "w", encoding="utf-8") as fh:
        json.dump(RULES, fh, ensure_ascii=False, indent=1)
    bgs = sorted(glob.glob(os.path.join(DATA, "bg", "*.mp4")))
    seed = 99 if FINAL else 2027 if HOLDOUT else 7
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    for i in range(n):
        if os.path.exists(os.path.join(OUT, f"c{i:03d}.json")):
            rng.random()
            continue

        class R:  # un singur generator pentru random și numpy, reproductibil
            def __getattr__(self, k):
                return getattr(rng, k)

            def uniform(self, a, b, size=None):
                return np_rng.uniform(a, b, size) if size is not None else rng.uniform(a, b)
        t = make_clip(i, R(), bgs, logos)
        print(t["id"], t["duration"], "logo", t["logo_seconds"], "said", t["said"], "forb", t["forbidden"], flush=True)


if __name__ == "__main__":
    main()
