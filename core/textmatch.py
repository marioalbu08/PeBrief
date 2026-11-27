"""Potrivirea frazelor din brief cu cuvintele recunoscute în vorbire.

Speech-to-text greșește ortografia ("Brisa" -> "Briza", "zero" -> "Zero,"),
deci comparăm pe forme normalizate (fără diacritice, fără punctuație) și cu o
distanță de editare, pe ferestre de cuvinte de lungimi apropiate. Așa prindem
și cazul "a spus «Brisa», dar brief-ul cere «Brisa Zero»" (potrivire parțială).
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

NUM = {"0": "zero", "1": "unu", "2": "doi", "3": "trei", "4": "patru", "5": "cinci",
       "6": "sase", "7": "sapte", "8": "opt", "9": "noua", "10": "zece"}


def norm(s: str) -> str:
    """Litere mici, fără diacritice și fără punctuație. Păstrează literele din orice
    alfabet (chirilic, grecesc): altfel o campanie în bulgară n-ar avea niciun cuvânt
    de comparat, iar cuvintele interzise n-ar fi găsite niciodată."""
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\w#]+|_", " ", s)
    return " ".join(NUM.get(w, w) for w in s.split())


def tokens(words: list[dict]) -> list[dict]:
    """Sparge cuvintele whisper în tokeni normalizați ("Coca-Cola" -> coca, cola),
    fiecare cu timpul cuvântului din care vine."""
    out = []
    for w in words:
        parts = norm(w["w"]).split()
        for p in parts:
            out.append({"w": w["w"] if len(parts) == 1 else p, "start": w["start"], "end": w["end"], "n": p})
    return out


def sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _pairwise(a: list[str], b: list[str]) -> float:
    """a și b au aceeași lungime. Fiecare cuvânt trebuie să semene cu perechea lui;
    altfel un cuvânt corect nu poate "acoperi" unul lipsă ("brisa e" != "brisa zero")."""
    sims = [sim(x, y) for x, y in zip(a, b)]
    m = sum(sims) / len(sims)
    return m if min(sims) >= 0.7 else min(sims)


def align(seg: list[str], tt: list[str]) -> float:
    """Scorul unei ferestre de cuvinte auzite față de fraza țintă, cuvânt cu cuvânt.
    Acceptă un singur cuvânt lipit ("brisazero") sau despărțit ("fa ra")."""
    if len(seg) == len(tt):
        return _pairwise(seg, tt)
    best = 0.0
    if len(seg) == len(tt) - 1:  # două cuvinte țintă rostite/scrise lipit
        for j in range(len(tt) - 1):
            t2 = tt[:j] + [tt[j] + tt[j + 1]] + tt[j + 2:]
            best = max(best, _pairwise(seg, t2) - 0.02)
    elif len(seg) == len(tt) + 1:  # un cuvânt țintă despărțit în două
        for j in range(len(seg) - 1):
            s2 = seg[:j] + [seg[j] + seg[j + 1]] + seg[j + 2:]
            best = max(best, _pairwise(s2, tt) - 0.02)
    return best


def find_phrase(words: list[dict], phrase: str, thresh: float = 0.82) -> dict:
    """words: [{w, start, end}]. Întoarce cea mai bună potrivire:
    {status: 'ok'|'partial'|'missing', score, start, end, heard}.
    """
    target = norm(phrase)
    if not target:
        return {"status": "ok", "score": 1.0}
    tt = target.split()
    k = len(tt)
    words = tokens(words)
    nw = [w["n"] for w in words]
    best = {"score": 0.0}
    for size in {max(1, k - 1), k, k + 1}:
        for i in range(0, max(0, len(words) - size + 1)):
            sc = align(nw[i:i + size], tt)
            if sc > best["score"]:
                best = {"score": sc, "start": words[i]["start"], "end": words[i + size - 1]["end"],
                        "heard": " ".join(w["w"].strip() for w in words[i:i + size])}
    if best["score"] >= thresh:
        best["status"] = "ok"
        return best
    # potrivire parțială: o parte din cuvintele frazei au fost rostite
    if k > 1:
        parts = target.split()
        hits = []
        for p in parts:
            for j, x in enumerate(nw):
                if len(p) >= 3 and x and sim(x, p) >= 0.85:
                    hits.append((p, j))
                    break
        if hits:  # o parte, sau toate în altă ordine ("zero de la brisa")
            j = hits[0][1]
            return {"status": "partial", "score": best["score"], "start": words[j]["start"],
                    "end": words[j]["end"], "heard": words[j]["w"].strip(),
                    "said": [h[0] for h in hits]}
    best["status"] = "missing"
    return best


def find_all(words: list[dict], phrase: str, thresh: float = 0.8) -> list[dict]:
    """Toate aparițiile unei fraze (pentru cuvintele interzise).

    Pragul e mai permisiv decât la frazele cerute: un cuvânt interzis ratat
    ajunge în campanie, iar o alarmă falsă costă doar o privire pe secunda
    arătată. Verificăm și ferestre cu un cuvânt în plus, lipite, fiindcă
    whisper desparte uneori cuvântul ("alcool" -> "alt col").
    """
    target = norm(phrase)
    tns = target.replace(" ", "")
    k = max(1, len(target.split()))
    if len(tns) < 5:  # cuvintele scurte se confundă ușor ("col" ~ "cola")
        thresh = max(thresh, 0.9)
    words = tokens(words)
    nw = [w["n"] for w in words]
    hits, i = [], 0
    while i <= len(words) - k:
        found = 0
        for size in (k, k + 1):
            if i + size > len(words):
                continue
            joined = " ".join(x for x in nw[i:i + size] if x)
            if not joined:
                continue
            # prefixul prinde formele flexionate din română: "alcool" -> "alcoolul"
            inflected = size == k and len(target) >= 4 and joined.startswith(target) and len(joined) - len(target) <= 4
            score = sim(joined.replace(" ", ""), tns)
            if size > k:
                score -= 0.03
            if (size == k and sim(joined, target) >= thresh) or inflected or (len(tns) >= 5 and score >= thresh):
                found = size
                break
        if found:
            hits.append({"start": words[i]["start"], "end": words[i + found - 1]["end"],
                         "heard": " ".join(w["w"].strip() for w in words[i:i + found])})
            i += found
        else:
            i += 1
    return hits


def caption_words(s: str) -> list[str]:
    """Cuvintele normalizate ale unei descrieri. Un cuvânt care începe cu # sau @ își
    păstrează semnul („@brand” nu e „#brand”), iar hashtag-urile lipite („#ad#brand”)
    se despart."""
    out = []
    for w in re.sub(r"([#@])", r" \1", s).split():
        mark = w[0] if w[0] in "#@" else ""
        parts = norm(w[1:] if mark else w).replace("#", " ").split()
        if parts:
            parts[0] = mark + parts[0]
        out += parts
    return out


def caption_has(caption: str, item: str) -> bool:
    """Descrierea conține elementul ca cuvinte întregi, în ordine: „#ad” nu e găsit în
    „#adidas”, „ad” nu e găsit în „adidas”, „@brand” nu e găsit în „#brand”."""
    it = caption_words(item)
    if not it:  # fără litere sau cifre (de exemplu un emoji): îl căutăm exact cum e scris
        return item.strip() in caption
    c = caption_words(caption)
    k = len(it)
    return any(c[i:i + k] == it for i in range(len(c) - k + 1))
