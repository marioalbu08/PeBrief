"""Vorbire -> cuvinte cu timp, local, cu faster-whisper (fără cloud)."""
from __future__ import annotations

import os
import threading
import wave

import numpy as np

_model = None
_lock = threading.Lock()
MODEL_NAME = os.environ.get("PEBRIEF_WHISPER", "medium")  # small greșește mult mai des (eval/REZULTATE.md)


def get_model():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
    return _model


def load_wav(path: str) -> np.ndarray:
    """WAV-ul mono, 16 kHz, pe 16 biți scos de `media.extract_audio`, ca float32 în [-1, 1]."""
    with wave.open(path, "rb") as w:
        if (w.getnchannels(), w.getsampwidth(), w.getframerate()) != (1, 2, 16000):
            raise ValueError("sunetul extras nu e mono, 16 kHz, 16 biți")
        data = w.readframes(w.getnframes())
    return np.frombuffer(data, np.int16).astype(np.float32) / 32768.0


def transcribe(wav: str, language: str = "ro", hint: str | None = None) -> dict:
    model = get_model()
    # Sunetul pleacă la whisper ca șir de numere, nu ca fișier: cu fișier, faster-whisper
    # îl deschide prin PyAV, iar PyAV 19 nu mai acceptă un argument pe care îl trimite.
    segs, info = model.transcribe(
        load_wav(wav),
        language=language or None,
        word_timestamps=True,
        vad_filter=True,
        beam_size=5,
        initial_prompt=hint,
        condition_on_previous_text=False,
    )
    words, text = [], []
    for s in segs:
        text.append(s.text.strip())
        for w in s.words or []:
            words.append({"w": w.word, "start": round(w.start, 2), "end": round(w.end, 2),
                          "p": round(w.probability, 3)})
    return {"text": " ".join(text), "words": words, "language": info.language}
