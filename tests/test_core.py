"""Teste rapide, fără video: python -m pytest tests  (sau python tests/test_core.py)"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.rules import BRIEF_TEMPLATE, parse_brief_offline  # noqa: E402
from core.textmatch import caption_has, find_all, find_phrase  # noqa: E402
from core.logo import to_intervals  # noqa: E402


def W(s):
    return [{"w": x, "start": float(i), "end": i + 0.5} for i, x in enumerate(s.split())]


def test_phrase_ok_with_asr_noise():
    assert find_phrase(W("azi încerc Brisa Zero, noua"), "Brisa Zero")["status"] == "ok"
    assert find_phrase(W("e fara zahar"), "fără zahăr")["status"] == "ok"
    assert find_phrase(W("încerc Brisa-Zero azi"), "Brisa Zero")["status"] == "ok"


def test_phrase_partial_and_missing():
    m = find_phrase(W("azi încerc Brisa, noua băutură"), "Brisa Zero")
    assert m["status"] == "partial" and m["start"] == 2.0
    assert find_phrase(W("azi încerc ceva nou"), "Brisa Zero")["status"] == "missing"


def test_forbidden():
    assert find_all(W("nu are alcool deloc"), "alcool")
    assert find_all(W("e fără alcoolul obișnuit"), "alcool")
    assert find_all(W("nu are alt col deloc"), "alcool")
    assert find_all(W("beau Coca-Cola azi"), "Cola")
    assert not find_all(W("am un calcul local"), "alcool")
    assert not find_all(W("nu are alt col deloc"), "Cola")
    assert not find_all(W("colaborare cu ei"), "Cola")


def test_caption():
    assert caption_has("Gust nou! #ad #brisazero", "#ad")
    assert not caption_has("Gust nou! #adidas", "#ad")
    assert caption_has("Gust nou #BrisaZero", "#brisazero")


def test_caption_matches_whole_words_only():
    # „@brisazero” (brandul etichetat) nu e același lucru cu hashtag-ul „#brisazero”
    assert not caption_has("Gust nou! #brisazero", "@brisazero")
    assert caption_has("Gust nou cu @brisazero", "@brisazero")
    assert not caption_has("Colaborare cu adidas", "ad")
    assert caption_has("Gust nou!#ad#brisazero", "#ad")  # hashtag-uri lipite


def test_other_alphabets():
    # o campanie în bulgară: cuvântul interzis se aude, hashtag-ul lipsește
    assert find_all(W("това е без алкохол"), "алкохол")
    assert not caption_has("нова напитка", "#реклама")
    assert caption_has("нова напитка #реклама", "#реклама")
    assert find_phrase(W("опитайте Бриза Зеро днес"), "Бриза Зеро")["status"] == "ok"


def test_offline_brief():
    r = parse_brief_offline(BRIEF_TEMPLATE)
    assert r["min_duration_s"] == 15 and r["max_duration_s"] == 30
    assert r["logo_min_seconds"] == 3
    assert r["must_say"] == ["Brisa Zero", "fără zahăr"]
    assert r["must_not_say"] == ["alcool", "Cola", "gratis"]
    assert r["caption_must_include"] == ["#ad", "#brisazero"]
    assert r["caption_must_not_include"] == ["#cocacola"]


def test_intervals_fill_gap_and_drop_isolated():
    f = [0, 1, 1, 0, 1, 1, 0, 0, 1, 0]
    s = [{"t": i * 0.25, "found": bool(x), "inliers": 12} for i, x in enumerate(f)]
    iv = to_intervals(s, 0.25)
    assert [(i["t0"], i["t1"]) for i in iv] == [(0.25, 1.5)]


if __name__ == "__main__":
    for k, fn in list(globals().items()):
        if k.startswith("test_"):
            fn()
            print("ok", k)
