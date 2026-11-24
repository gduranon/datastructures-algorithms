"""Huellas de voz locales para distinguir interlocutores. `python speakers.py` descarga el modelo (29 MB)."""
from __future__ import annotations

import hashlib
import io
import threading
import wave
from pathlib import Path

from providers import env

try:
    import numpy as np
    import sherpa_onnx
except ImportError:
    np = sherpa_onnx = None

MODEL = Path(__file__).parent / "models" / "speaker.onnx"
URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
       "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx")
SHA256 = "98daf9bcf1c8abf3db374fec4c27a5eda7c58705bb3f180d057b085a72a88bb5"
try:
    THRESHOLD = float(env("SPEAKER_THRESHOLD", "0.55"))
except ValueError:
    THRESHOLD = 0.55
MIN_NEW = 1.5  # segundos de audio para dar de alta una voz nueva

_lock = threading.Lock()
_extractor = None


def available() -> bool:
    return sherpa_onnx is not None and MODEL.exists()


def embed(audio: bytes):
    """(vector normalizado, segundos) de un WAV PCM16 mono de 16 kHz, o None."""
    global _extractor
    if not available() or audio[:4] != b"RIFF":
        return None
    with wave.open(io.BytesIO(audio)) as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (16000, 1, 2):
            return None
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    # Los silencios ensucian la huella: se descartan los tramos de 20 ms muy débiles.
    frames = x[:len(x) // 320 * 320].reshape(-1, 320)
    if not len(frames):
        return None
    rms = np.sqrt((frames ** 2).mean(axis=1))
    x = frames[rms > max(0.003, rms.max() * 0.05)].reshape(-1)
    seconds = len(x) / 16000
    if seconds < 0.5:
        return None
    with _lock:
        if _extractor is None:
            _extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
                sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(MODEL), num_threads=1))
        st = _extractor.create_stream()
        st.accept_waveform(16000, x)
        st.input_finished()
        if not _extractor.is_ready(st):
            return None
        v = np.array(_extractor.compute(st))
    norm = np.linalg.norm(v)
    return (v / norm, seconds) if norm else None


class Speakers:
    """Agrupa voces a medida que llegan. Solo vive en memoria."""

    def __init__(self):
        self.items: dict[int, dict] = {}
        self._next = 1

    def assign(self, emb) -> int | None:
        if emb is None:
            return None
        v, seconds = emb
        scores = {i: float(s["sum"] @ v / np.linalg.norm(s["sum"])) for i, s in self.items.items()}
        best = max(scores, key=scores.get) if scores else None
        if best is not None and scores[best] >= THRESHOLD:
            self.items[best]["sum"] = self.items[best]["sum"] + v * min(seconds, 5)
            return best
        if seconds < MIN_NEW:  # poco audio: se atribuye solo si se parece bastante
            return best if best is not None and scores[best] >= THRESHOLD - 0.1 else None
        sid, self._next = self._next, self._next + 1
        self.items[sid] = {"name": f"Voz {sid}", "me": False, "sum": v * min(seconds, 5)}
        return sid

    def merge(self, src: int, dst: int):
        a = self.items.pop(src)
        b = self.items[dst]
        b["sum"] = b["sum"] + a["sum"]
        b["me"] = b["me"] or a["me"]

    def label(self, sid) -> str:
        s = self.items.get(sid)
        return "Voz desconocida" if s is None else s["name"] + (" (yo)" if s["me"] else "")

    def public(self) -> list[dict]:
        return [{"id": i, "name": s["name"], "me": s["me"]} for i, s in self.items.items()]


if __name__ == "__main__":
    import httpx

    data = httpx.get(URL, follow_redirects=True, timeout=120).raise_for_status().content
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise SystemExit("El modelo descargado no coincide con el esperado.")
    MODEL.parent.mkdir(exist_ok=True)
    MODEL.write_bytes(data)
    print("Modelo listo:", MODEL)
