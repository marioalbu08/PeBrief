"""Vorbire -> cuvinte cu timp, local, cu faster-whisper (fără cloud)."""
from __future__ import annotations

import os
import threading

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


def transcribe(wav: str, language: str = "ro", hint: str | None = None) -> dict:
    model = get_model()
    segs, info = model.transcribe(
        wav,
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
