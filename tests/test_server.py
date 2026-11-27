"""Serverul: banii, încărcările și repornirea. Rulează pe un folder `data/` temporar.

python -m pytest tests
"""
import os
import sys
import tempfile
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["PEBRIEF_DATA"] = tempfile.mkdtemp(prefix="pebrief-test-")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
from core.rules import BRIEF_TEMPLATE  # noqa: E402


class SyncPool:
    """Verificarea rulează pe loc, ca testul să vadă verdictul imediat."""

    def submit(self, fn, *args):
        fn(*args)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(server, "pool", SyncPool())
    monkeypatch.setattr(server, "run_check",
                        lambda *a, **k: {"pass": True, "checks": [], "manual": [], "timeline": {}})
    return TestClient(server.app)


def new_campaign(client, fee=1500):
    r = client.post("/api/campaigns", data={"title": "test", "brief": BRIEF_TEMPLATE,
                                            "fee": str(fee), "use_claude": "false"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def upload(client, cid, creator, name="draft.mp4", body=b"\0" * 2048):
    return client.post(f"/api/campaigns/{cid}/submissions", data={"creator": creator, "caption": ""},
                       files={"video": (name, body, "video/mp4")})


def ledger_kinds(client, cid):
    return [x["kind"] for x in client.get(f"/api/campaigns/{cid}").json()["ledger"]]


def test_double_click_on_publish_pays_once(client, monkeypatch):
    """Două cereri „Am postat” trimise deodată (dublu clic) nu plătesc de două ori."""
    cid = new_campaign(client)
    sid = upload(client, cid, "bob").json()["id"]
    barrier = threading.Barrier(2, timeout=3)
    real = server.db_lock

    class Gate:  # ține ambele cereri până au trecut amândouă de citirea statusului
        def __enter__(self):
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
            return real.__enter__()

        def __exit__(self, *exc):
            return real.__exit__(*exc)

    monkeypatch.setattr(server, "db_lock", Gate())
    results = []

    def go():
        try:
            server.publish(sid, link="https://www.tiktok.com/@bob/video/1")
            results.append("ok")
        except HTTPException as e:
            results.append(e.status_code)

    threads = [threading.Thread(target=go) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    monkeypatch.setattr(server, "db_lock", real)
    assert ledger_kinds(client, cid).count("plătit") == 1
    assert sorted(map(str, results)) == ["400", "ok"]


def test_same_creator_is_paid_once_per_campaign(client):
    """Un creator aprobat care mai încarcă o variantă nu primește încă un onorariu."""
    cid = new_campaign(client)
    a = upload(client, cid, "ana").json()["id"]
    b = upload(client, cid, "ana").json()["id"]
    assert client.post(f"/api/submissions/{a}/publish", data={"link": "https://t.co/1"}).status_code == 200
    assert client.post(f"/api/submissions/{b}/publish", data={"link": "https://t.co/2"}).status_code == 400
    kinds = ledger_kinds(client, cid)
    assert kinds.count("blocat") == 1 and kinds.count("plătit") == 1


def test_creator_name_is_trimmed(client):
    """Tastatura telefonului lasă un spațiu după nume: tot a doua încercare e."""
    cid = new_campaign(client)
    upload(client, cid, "dana ")
    s2 = upload(client, cid, "dana").json()["id"]
    assert client.get(f"/api/submissions/{s2}").json()["attempt"] == 2
    assert upload(client, cid, "   ").status_code == 400


def test_upload_is_never_served_as_a_page(client):
    """Un fișier „x.html” încărcat ca draft nu ajunge servit ca pagină pe adresa aplicației."""
    cid = new_campaign(client)
    sid = upload(client, cid, "eve", name="x.html", body=b"<script>alert(1)</script>" + b" " * 2048).json()["id"]
    r = client.get(f"/api/submissions/{sid}/video")
    assert r.status_code == 200
    assert "html" not in r.headers["content-type"]


def test_draft_left_in_check_by_a_restart_is_checked_again(client):
    """Serverul oprit în timpul unei verificări: la repornire, draftul nu rămâne „în verificare” la nesfârșit."""
    cid = new_campaign(client)
    sid = upload(client, cid, "radu").json()["id"]
    with server.db_lock, server.db() as c:  # starea lăsată de un server oprit la jumătate
        c.execute("update submissions set status='în verificare', verdict=null where id=?", (sid,))
        c.execute("delete from ledger where submission=?", (sid,))
    server.resume_pending()
    assert client.get(f"/api/submissions/{sid}").json()["status"] == "aprobat"
