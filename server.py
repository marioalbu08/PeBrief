"""PeBrief: serverul.

Pornire:  python server.py         (apoi http://localhost:8765)
Telefoanele din aceeași rețea Wi-Fi intră pe adresa LAN afișată la pornire.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import socket
import sqlite3
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from core.check import run_check
from core.paths import resolve, to_stored
from core.rules import BRIEF_TEMPLATE, normalize_rules, parse_brief, parse_brief_offline

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("PEBRIEF_DATA") or os.path.join(ROOT, "data")  # testele folosesc un folder temporar
DB = os.path.join(DATA, "pebrief.db")
PORT = int(os.environ.get("PEBRIEF_PORT", "8765"))
os.makedirs(DATA, exist_ok=True)

app = FastAPI(title="PeBrief")
pool = ThreadPoolExecutor(max_workers=1)  # whisper + SIFT folosesc deja toate nucleele
progress: dict[str, dict] = {}
db_lock = threading.Lock()


def db():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with db() as c:
        c.executescript("""
        create table if not exists campaigns(
          id text primary key, title text, brief text, rules text, rules_source text,
          logo text, fee real, created real);
        create table if not exists submissions(
          id text primary key, campaign text, creator text, caption text, video text,
          status text, verdict text, attempt integer, created real, link text, paid_at real);
        create table if not exists ledger(
          id integer primary key autoincrement, campaign text, submission text,
          kind text, amount real, note text, at real);
        """)


def migrate_paths():
    """Versiunile vechi scriau căi absolute; după o mutare a folderului ele nu mai există."""
    with db_lock, db() as c:
        for table, col in (("campaigns", "logo"), ("submissions", "video")):
            for r in c.execute(f"select id, {col} from {table}").fetchall():
                old = r[col]
                new = to_stored(resolve(old, DATA), DATA)
                if new != old:
                    c.execute(f"update {table} set {col}=? where id=?", (new, r["id"]))


def data_file(stored: str | None) -> str:
    """Fișierul de pe disc pentru o cale din baza de date, sau 404 dacă lipsește."""
    p = resolve(stored, DATA)
    if not p or not os.path.exists(p):
        raise HTTPException(404, "fișierul nu mai există")
    return p


def row(r):
    return dict(r) if r else None


def campaign_out(r):
    d = row(r)
    d["rules"] = json.loads(d["rules"])
    d["has_logo"] = bool(d.pop("logo"))
    return d


def sub_out(r):
    d = row(r)
    d["verdict"] = json.loads(d["verdict"]) if d["verdict"] else None
    d["progress"] = progress.get(d["id"])
    d.pop("video", None)
    return d


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


# ---------------------------------------------------------------- campanii

@app.get("/api/info")
def info():
    return {"lan": f"http://{lan_ip()}:{PORT}", "template": BRIEF_TEMPLATE}


@app.get("/api/campaigns")
def campaigns():
    with db() as c:
        rs = c.execute("select * from campaigns order by created desc").fetchall()
        out = []
        for r in rs:
            d = campaign_out(r)
            st = c.execute("select status, count(*) n from submissions where campaign=? group by status",
                           (d["id"],)).fetchall()
            d["counts"] = {s["status"]: s["n"] for s in st}
            out.append(d)
    return out


@app.post("/api/campaigns")
def create_campaign(title: str = Form(...), brief: str = Form(...), fee: float = Form(0),
                    use_claude: bool = Form(True), logo: UploadFile | None = File(None)):
    cid = uuid.uuid4().hex[:8]
    rules, source = parse_brief(brief, use_claude=use_claude)
    logo_path = None
    if logo is not None and logo.filename:
        d = os.path.join(DATA, "campaigns", cid)
        os.makedirs(d, exist_ok=True)
        logo_path = os.path.join(d, "logo" + safe_ext(logo.filename, IMAGE_EXT, ".png"))
        with open(logo_path, "wb") as fh:
            shutil.copyfileobj(logo.file, fh)
        try:
            from core.logo import load_logo
            load_logo(logo_path)
        except ValueError as e:
            raise HTTPException(400, str(e))
    with db_lock, db() as c:
        c.execute("insert into campaigns values(?,?,?,?,?,?,?,?)",
                  (cid, title, brief, json.dumps(rules, ensure_ascii=False), source,
                   to_stored(logo_path, DATA), fee, time.time()))
    return get_campaign(cid)


@app.get("/api/campaigns/{cid}")
def get_campaign(cid: str):
    with db() as c:
        r = c.execute("select * from campaigns where id=?", (cid,)).fetchone()
        if not r:
            raise HTTPException(404, "campania nu există")
        d = campaign_out(r)
        d["submissions"] = [sub_out(s) for s in c.execute(
            "select * from submissions where campaign=? order by created desc", (cid,)).fetchall()]
        d["ledger"] = [row(x) for x in c.execute(
            "select * from ledger where campaign=? order by at", (cid,)).fetchall()]
    return d


@app.put("/api/campaigns/{cid}/rules")
def put_rules(cid: str, rules: dict):
    rules = normalize_rules(rules)
    with db_lock, db() as c:
        c.execute("update campaigns set rules=?, rules_source='editat' where id=?",
                  (json.dumps(rules, ensure_ascii=False), cid))
    return get_campaign(cid)


@app.get("/api/campaigns/{cid}/logo")
def get_logo(cid: str):
    with db() as c:
        r = c.execute("select logo from campaigns where id=?", (cid,)).fetchone()
    if not r or not r["logo"]:
        raise HTTPException(404)
    return FileResponse(data_file(r["logo"]))


# ---------------------------------------------------------------- încărcări

def process(sid: str):
    with db() as c:
        s = c.execute("select * from submissions where id=?", (sid,)).fetchone()
        camp = c.execute("select * from campaigns where id=?", (s["campaign"],)).fetchone()
    rules = json.loads(camp["rules"])

    def prog(p, msg):
        progress[sid] = {"p": round(p, 3), "msg": msg}

    try:
        v = run_check(resolve(s["video"], DATA), rules, s["caption"] or "", resolve(camp["logo"], DATA),
                      frames_dir=os.path.join(DATA, "submissions", sid, "frames"), progress=prog)
        status = "aprobat" if v["pass"] else "de refăcut"
    except Exception as e:  # noqa: BLE001
        v = {"error": str(e), "pass": False, "checks": []}
        status = "eroare"
    with db_lock, db() as c:
        c.execute("update submissions set verdict=?, status=? where id=?",
                  (json.dumps(v, ensure_ascii=False), status, sid))
        # Onorariul e per creator: o a doua variantă aprobată a aceluiași creator nu mai rezervă încă unul.
        already = c.execute("select 1 from submissions where campaign=? and creator=? and id<>? "
                            "and status in ('aprobat', 'plătit')", (s["campaign"], s["creator"], sid)).fetchone()
        if status == "aprobat" and not already:
            c.execute("insert into ledger(campaign, submission, kind, amount, note, at) values(?,?,?,?,?,?)",
                      (s["campaign"], sid, "blocat", camp["fee"],
                       f"{s['creator']}: draft aprobat, onorariul e rezervat până la publicare", time.time()))
    progress.pop(sid, None)


def resume_pending():
    """Un server oprit în timpul unei verificări lasă drafturi „în verificare”. La pornire le verificăm din nou."""
    with db() as c:
        ids = [r["id"] for r in c.execute(
            "select id from submissions where status='în verificare' order by created").fetchall()]
    for sid in ids:
        progress[sid] = {"p": 0.0, "msg": "În coadă"}
        pool.submit(process, sid)


VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".3gp", ".avi"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def safe_ext(filename: str | None, allowed: set[str], default: str) -> str:
    """Extensia fișierului încărcat, doar dacă e una așteptată: un „x.html” nu ajunge servit ca pagină."""
    ext = os.path.splitext(filename or "")[1].lower()
    return ext if ext in allowed else default


@app.post("/api/campaigns/{cid}/submissions")
def submit(cid: str, creator: str = Form(...), caption: str = Form(""), video: UploadFile = File(...)):
    creator = creator.strip()  # tastatura telefonului lasă des un spațiu după nume
    if not creator:
        raise HTTPException(400, "scrie-ți numele sau contul")
    with db() as c:
        if not c.execute("select 1 from campaigns where id=?", (cid,)).fetchone():
            raise HTTPException(404, "campania nu există")
    sid = uuid.uuid4().hex[:10]
    d = os.path.join(DATA, "submissions", sid)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "video" + safe_ext(video.filename, VIDEO_EXT, ".mp4"))
    with open(path, "wb") as fh:
        shutil.copyfileobj(video.file, fh)
    with db_lock, db() as c:
        attempt = c.execute("select count(*) from submissions where campaign=? and creator=?",
                            (cid, creator)).fetchone()[0] + 1
        c.execute("insert into submissions(id, campaign, creator, caption, video, status, attempt, created) "
                  "values(?,?,?,?,?,?,?,?)", (sid, cid, creator, caption, to_stored(path, DATA),
                                              "în verificare", attempt, time.time()))
    progress[sid] = {"p": 0.0, "msg": "În coadă"}
    pool.submit(process, sid)
    return {"id": sid}


@app.get("/api/submissions/{sid}")
def get_sub(sid: str):
    with db() as c:
        r = c.execute("select * from submissions where id=?", (sid,)).fetchone()
    if not r:
        raise HTTPException(404)
    return sub_out(r)


@app.get("/api/submissions/{sid}/video")
def get_video(sid: str):
    with db() as c:
        r = c.execute("select video from submissions where id=?", (sid,)).fetchone()
    if not r:
        raise HTTPException(404)
    return FileResponse(data_file(r["video"]))


@app.get("/api/submissions/{sid}/frame/{ms}")
def get_frame(sid: str, ms: int):
    p = os.path.join(DATA, "submissions", sid, "frames", f"t{ms}.jpg")
    if not os.path.exists(p):
        raise HTTPException(404)
    return FileResponse(p)


@app.post("/api/submissions/{sid}/publish")
def publish(sid: str, link: str = Form(...)):
    link = link.strip()
    if not link.startswith(("http://", "https://")):
        raise HTTPException(400, "linkul trebuie să înceapă cu https://")
    now = time.time()
    # Citirea statusului și plata se fac sub același lacăt: un dublu clic pe „Am postat”
    # trimite două cereri deodată, iar amândouă ar vedea „aprobat” și ar plăti.
    with db_lock, db() as c:
        s = c.execute("select * from submissions where id=?", (sid,)).fetchone()
        if not s:
            raise HTTPException(404)
        if s["status"] != "aprobat":
            raise HTTPException(400, "doar un draft aprobat poate fi publicat")
        if c.execute("select 1 from submissions where campaign=? and creator=? and status='plătit'",
                     (s["campaign"], s["creator"])).fetchone():
            raise HTTPException(400, f"onorariul pentru {s['creator']} e deja plătit în campania asta")
        camp = c.execute("select * from campaigns where id=?", (s["campaign"],)).fetchone()
        c.execute("update submissions set status='plătit', link=?, paid_at=? where id=?", (link, now, sid))
        c.execute("insert into ledger(campaign, submission, kind, amount, note, at) values(?,?,?,?,?,?)",
                  (s["campaign"], sid, "plătit", camp["fee"], f"{s['creator']}: publicat la {link}", now))
    return get_sub(sid)


@app.get("/api/qr")
def qr(url: str):
    import qrcode
    img = qrcode.make(url, border=2, box_size=8)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(buf.getvalue(), media_type="image/png")


# ---------------------------------------------------------------- demo

def seed_demo():
    with db() as c:
        if c.execute("select count(*) from campaigns").fetchone()[0]:
            return
    logo = os.path.join(ROOT, "eval", "data", "logo_brisa.png")
    if not os.path.exists(logo):
        return
    d = os.path.join(DATA, "campaigns", "demo")
    os.makedirs(d, exist_ok=True)
    shutil.copy(logo, os.path.join(d, "logo.png"))
    rules = parse_brief_offline(BRIEF_TEMPLATE)
    with db_lock, db() as c:
        c.execute("insert into campaigns values(?,?,?,?,?,?,?,?)",
                  ("demo", "Brisa Zero · vara 2027", BRIEF_TEMPLATE, json.dumps(rules, ensure_ascii=False),
                   "offline", to_stored(os.path.join(d, "logo.png"), DATA), 1500, time.time()))


init_db()
migrate_paths()
seed_demo()
resume_pending()
app.mount("/", StaticFiles(directory=os.path.join(ROOT, "static"), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    try:  # în log sau într-o consolă fără UTF-8, diacriticele nu mai opresc pornirea
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    print(f"\n  PeBrief rulează:  http://localhost:{PORT}\n  De pe telefon (același Wi-Fi):  http://{lan_ip()}:{PORT}\n")
    # încărcăm whisper din timp, ca primul clip să nu aștepte
    threading.Thread(target=lambda: __import__("core.speech", fromlist=["x"]).get_model(), daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")
