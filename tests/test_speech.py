"""Vorbirea: whisper primește sunetul ca șir de numere, nu ca fișier.

Cu fișier, faster-whisper îl deschide prin PyAV, iar PyAV 19 (instalat implicit
din noiembrie 2026) a scos un argument pe care faster-whisper 1.2.1 încă îl
trimite: pe o instalare curată, fiecare clip ieșea „eroare”.

python -m pytest tests
"""
import os
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import speech  # noqa: E402


def write_wav(path, samples):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.asarray(samples) * 32767).astype(np.int16).tobytes())


def test_whisper_gets_samples_not_a_file(tmp_path, monkeypatch):
    seen = {}

    class FakeModel:
        def transcribe(self, audio, **kw):
            seen["audio"] = audio

            class Info:
                language = "ro"
            return iter([]), Info()

    monkeypatch.setattr(speech, "get_model", lambda: FakeModel())
    tone = 0.5 * np.sin(2 * np.pi * 440 * np.arange(16000) / 16000)
    write_wav(tmp_path / "a.wav", tone)
    speech.transcribe(str(tmp_path / "a.wav"))
    audio = seen["audio"]
    assert isinstance(audio, np.ndarray) and audio.dtype == np.float32
    assert len(audio) == 16000 and abs(float(np.abs(audio).max()) - 0.5) < 0.01
