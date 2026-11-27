"""Verdictul pe clipuri mici, generate în test (câteva secunde, fără whisper).

python -m pytest tests
"""
import os
import subprocess
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from core import media  # noqa: E402
from core.check import run_check  # noqa: E402
from core.rules import normalize_rules  # noqa: E402

LOGO = os.path.join(ROOT, "eval", "data", "logo_brisa.png")


def write_clip(path, seconds, fps=30, size=(360, 640), logo_from=None):
    """Clip vertical gri, cu logo-ul lipit de la `logo_from` până la final."""
    w, h = size
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    rng = np.random.default_rng(0)
    logo = cv2.imread(LOGO, cv2.IMREAD_UNCHANGED)
    lw = int(w * 0.8)
    logo = cv2.resize(logo, (lw, int(lw * logo.shape[0] / logo.shape[1])), interpolation=cv2.INTER_AREA)
    a = logo[:, :, 3:4].astype(np.float32) / 255
    for f in range(int(round(seconds * fps))):
        fr = np.clip(rng.normal(110, 12, (h, w, 3)), 0, 255).astype(np.uint8)
        if logo_from is not None and f / fps >= logo_from:
            y, x = h // 2 - logo.shape[0] // 2, (w - lw) // 2
            roi = fr[y:y + logo.shape[0], x:x + lw].astype(np.float32)
            fr[y:y + logo.shape[0], x:x + lw] = (logo[:, :, :3] * a + roi * (1 - a)).astype(np.uint8)
        vw.write(fr)
    vw.release()
    return path


def test_variable_frame_rate_keeps_real_time(tmp_path):
    """Telefoanele filmează cu cadre pe secundă variabile: secunda unui cadru e cea reală."""
    # 2 s negru la 30 de cadre pe secundă, apoi 2 s alb la 10 (ca un telefon care intră în lumină slabă)
    out = tmp_path / "vfr.mp4"
    subprocess.run([media.ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=160x288:r=30:d=4",
                    "-vf", r"drawbox=enable='gte(t,2)':color=white:t=fill,select='lt(t\,2)+not(mod(n\,3))'",
                    "-fps_mode", "vfr", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
    samples = [(t, fr.mean() > 128) for t, fr in media.sample_frames(str(out), 0.25)]
    white = [t for t, w in samples if w]
    assert abs(white[0] - 2.0) <= 0.1, samples       # albul începe la 2 s
    assert samples[-1][0] >= 3.5, samples            # și ține până aproape de 4 s


def test_logo_at_the_end_is_not_counted_past_the_end(tmp_path):
    """Logo-ul se vede în ultimele 2,8 s ale clipului, iar brief-ul cere 3 s: nu trece."""
    clip = write_clip(str(tmp_path / "end.mp4"), seconds=3.8, logo_from=1.0)
    v = run_check(clip, normalize_rules({"logo_min_seconds": 3}), logo_path=LOGO)
    logo = next(c for c in v["checks"] if c["id"] == "logo")
    assert logo["value"] <= 3.8 - 1.0 + 0.01, logo
    assert not logo["pass"] and not v["pass"]


def test_logo_rule_without_logo_image_is_not_silently_skipped(tmp_path):
    """Brief-ul cere logo, dar campania n-are imaginea logo-ului: un om trebuie să verifice."""
    clip = write_clip(str(tmp_path / "c.mp4"), seconds=1.0)
    v = run_check(clip, normalize_rules({"min_duration_s": 0.5, "max_duration_s": 5, "logo_min_seconds": 3}))
    assert any("logo" in m.lower() for m in v["manual"])


def test_brief_without_checkable_rules_says_why(tmp_path):
    """Un brief din care nu iese nicio regulă verificabilă nu dă „De refăcut: 0 probleme”."""
    clip = write_clip(str(tmp_path / "c.mp4"), seconds=1.0)
    v = run_check(clip, normalize_rules({"manual": ["ton vesel"]}))
    assert not v["pass"]
    assert [c for c in v["checks"] if not c["pass"]]
