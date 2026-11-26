"""Brief -> reguli verificabile.

Un brief scris liber devine un "contract" cu reguli pe care mașina le poate
verifica. Ce nu se poate verifica automat ajunge în `manual`, ca să-l vadă un
om, nu să fie ignorat în tăcere.

Două căi:
  1. Claude (prin `claude -p` sau ANTHROPIC_API_KEY), pentru brief-uri reale.
  2. Un parser cu reguli, care merge offline, pentru brief-urile scrise după
     șablonul din `BRIEF_TEMPLATE`.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

DEFAULT_RULES = {
    "brand": "",
    "language": "ro",
    "min_duration_s": None,
    "max_duration_s": None,
    "logo_min_seconds": None,
    "must_say": [],
    "must_not_say": [],
    "caption_must_include": [],
    "caption_must_not_include": [],
    "manual": [],
}

BRIEF_TEMPLATE = """Brand: Brisa Zero
Durată: 15-30 secunde
Logo vizibil: minim 3 secunde
Trebuie să spui: "Brisa Zero", "fără zahăr"
Nu spune: alcool, Cola, gratis
Descriere obligatoriu: #ad, #brisazero
Descriere interzis: #cocacola
Altele: filmat la lumină naturală, fără alți creatori în cadru
"""

SCHEMA_TEXT = """{
  "brand": string,
  "language": "ro" | "en" | ...,
  "min_duration_s": number | null,
  "max_duration_s": number | null,
  "logo_min_seconds": number | null,   // câte secunde trebuie să se vadă logo-ul
  "must_say": [string],                // fraze exacte care trebuie rostite
  "must_not_say": [string],            // cuvinte/fraze interzise în vorbire
  "caption_must_include": [string],    // hashtag-uri sau text obligatoriu în descriere
  "caption_must_not_include": [string],
  "manual": [string]                   // cerințe pe care un program nu le poate verifica sigur
}"""

PROMPT = """Transformă brief-ul de campanie de mai jos în reguli verificabile.
Răspunde DOAR cu un obiect JSON, fără text în jur, după schema:
{schema}

Reguli:
- Pune în must_say doar ce brief-ul cere explicit să fie spus. Păstrează forma exactă.
- Dacă brief-ul cere dezvăluirea colaborării (ex. "marchează ca reclamă"), adaugă "#ad" în caption_must_include.
- "Logo-ul / produsul / doza / ambalajul să se vadă N secunde" -> logo_min_seconds = N
  (sistemul caută imaginea de brand încărcată de agenție: logo sau poza produsului).
- Orice altă cerință vizuală sau de ton merge în manual.
- Nu inventa cerințe care nu sunt în brief.

BRIEF:
<<<
{brief}
>>>"""


def normalize_rules(r: dict) -> dict:
    out = dict(DEFAULT_RULES)
    for k in DEFAULT_RULES:
        if k in r and r[k] is not None:
            out[k] = r[k]
    for k in ("must_say", "must_not_say", "caption_must_include",
              "caption_must_not_include", "manual"):
        v = out[k]
        if isinstance(v, str):
            v = [v]
        out[k] = [str(x).strip() for x in v if str(x).strip()]
    for k in ("min_duration_s", "max_duration_s", "logo_min_seconds"):
        if out[k] is not None:
            try:
                out[k] = float(out[k])
            except (TypeError, ValueError):
                out[k] = None
    return out


# ---------------------------------------------------------------- offline parser

def _items(s: str) -> list[str]:
    quoted = re.findall(r'[„"“”«]([^"“”„«»]+)[”"“»]', s)
    if quoted:
        return [q.strip() for q in quoted]
    return [p.strip(" .;") for p in re.split(r"[,;]", s) if p.strip(" .;")]


def parse_brief_offline(brief: str) -> dict:
    r: dict = {"manual": []}
    for raw in brief.splitlines():
        line = raw.strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        k = key.lower()
        nums = [float(x.replace(",", ".")) for x in re.findall(r"\d+(?:[.,]\d+)?", val)]
        if k.startswith("brand"):
            r["brand"] = val.strip()
        elif "durat" in k or "duration" in k:
            if len(nums) >= 2:
                r["min_duration_s"], r["max_duration_s"] = nums[0], nums[1]
            elif nums and re.search(r"max", val, re.I):
                r["max_duration_s"] = nums[0]
            elif nums:
                r["min_duration_s"] = nums[0]
        elif "logo" in k:
            if nums:
                r["logo_min_seconds"] = nums[0]
        elif re.search(r"nu (spune|zice|men)", k) or "interzis" in k and "descri" not in k:
            r["must_not_say"] = _items(val)
        elif re.search(r"(spui|spune|men[tț]ion|zici|say)", k):
            r["must_say"] = _items(val)
        elif ("descri" in k or "caption" in k) and ("interzis" in k or "nu" in k.split()):
            r["caption_must_not_include"] = _items(val)
        elif "descri" in k or "caption" in k or "hashtag" in k:
            r["caption_must_include"] = _items(val)
        elif "limb" in k or "language" in k:
            r["language"] = "en" if "engl" in val.lower() or val.strip().lower() == "en" else "ro"
        else:
            r["manual"].append(val.strip() if k.startswith(("alt", "other")) else line)
    return normalize_rules(r)


# ---------------------------------------------------------------- Claude parser

def _extract_json(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("răspunsul nu conține JSON")
    return json.loads(m.group(0))


def parse_brief_claude(brief: str, timeout: int = 120) -> dict:
    prompt = PROMPT.format(schema=SCHEMA_TEXT, brief=brief)
    if os.environ.get("ANTHROPIC_API_KEY"):
        import anthropic
        client = anthropic.Anthropic()
        msg = client.messages.create(
            model=os.environ.get("PEBRIEF_MODEL", "claude-haiku-5-5"),
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        return normalize_rules(_extract_json(msg.content[0].text))
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("nici ANTHROPIC_API_KEY, nici CLI-ul claude")
    p = subprocess.run(
        [exe, "-p", "--output-format", "json", "--model", "haiku"],
        input=prompt, capture_output=True, text=True, encoding="utf-8",
        timeout=timeout,
    )
    if p.returncode != 0:
        raise RuntimeError(p.stderr.strip()[:300] or "claude -p a eșuat")
    outer = json.loads(p.stdout)
    return normalize_rules(_extract_json(outer.get("result", "")))


def parse_brief(brief: str, use_claude: bool = True) -> tuple[dict, str]:
    """Întoarce (reguli, sursa). Sursa e 'claude' sau 'offline'."""
    if use_claude:
        try:
            return parse_brief_claude(brief), "claude"
        except Exception as e:  # noqa: BLE001
            print("[rules] Claude indisponibil, folosesc parserul offline:", e)
    return parse_brief_offline(brief), "offline"


if __name__ == "__main__":
    print(json.dumps(parse_brief_offline(BRIEF_TEMPLATE), ensure_ascii=False, indent=2))
