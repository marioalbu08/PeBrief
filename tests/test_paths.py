"""Căile din baza de date rezistă la mutarea folderului: python -m pytest tests"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.paths import resolve, to_stored  # noqa: E402


def test_stored_is_relative_and_resolves_back(tmp_path):
    data = tmp_path / "data"
    f = data / "submissions" / "abc" / "video.mp4"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    stored = to_stored(str(f), str(data))
    assert stored == "submissions/abc/video.mp4"
    assert os.path.samefile(resolve(stored, str(data)), f)


def test_old_absolute_path_from_moved_folder(tmp_path):
    data = tmp_path / "proiecte" / "pebrief" / "data"
    f = data / "campaigns" / "demo" / "logo.png"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    old = r"C:\Users\cineva\Desktop\7d\pebrief\data\campaigns\demo\logo.png"
    assert os.path.samefile(resolve(old, str(data)), f)
    assert to_stored(resolve(old, str(data)), str(data)) == "campaigns/demo/logo.png"


def test_missing_and_empty(tmp_path):
    data = str(tmp_path / "data")
    assert resolve(None, data) is None and to_stored(None, data) is None
    old = r"C:\nicaieri\data\lipsa.png"
    assert resolve(old, data) == old  # lipsește oriunde: rămâne cum era, serverul dă 404
