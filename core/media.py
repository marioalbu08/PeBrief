"""Citirea clipului: durată, cadre eșantionate, audio 16 kHz."""
from __future__ import annotations

import os
import subprocess
import tempfile

import cv2
import numpy as np


def ffmpeg_exe() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def probe(path: str) -> dict:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError("clipul nu poate fi deschis")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    n = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    dur = n / fps if n > 0 else 0.0
    return {"fps": fps, "frames": int(n), "width": w, "height": h, "duration": dur}


def sample_frames(path: str, step_s: float, max_side: int = 720):
    """Generează (t, cadru BGR redimensionat), câte un cadru la `step_s` secunde.

    Citește secvențial (grab) în loc de seek, fiindcă seek-ul pe H.264 de
    telefon e lent și uneori inexact.
    """
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    idx = 0
    next_t = 0.0
    while True:
        ok = cap.grab()
        if not ok:
            break
        t = idx / fps
        if t + 1e-6 >= next_t:
            ok, frame = cap.retrieve()
            if not ok:
                break
            h, w = frame.shape[:2]
            s = max_side / max(h, w)
            if s < 1:
                frame = cv2.resize(frame, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
            yield t, frame
            next_t += step_s
        idx += 1
    cap.release()


def frame_at(path: str, t: float, max_side: int = 480) -> np.ndarray | None:
    cap = cv2.VideoCapture(path)
    cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None
    h, w = frame.shape[:2]
    s = max_side / max(h, w)
    if s < 1:
        frame = cv2.resize(frame, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return frame


def extract_audio(path: str) -> str | None:
    """Extrage audio mono 16 kHz într-un WAV temporar. None dacă nu are audio."""
    fd, wav = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    p = subprocess.run(
        [ffmpeg_exe(), "-y", "-loglevel", "error", "-i", path, "-vn", "-ac", "1",
         "-ar", "16000", "-f", "wav", wav],
        capture_output=True,
    )
    if p.returncode != 0 or os.path.getsize(wav) < 1000:
        os.unlink(wav)
        return None
    return wav
