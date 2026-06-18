from __future__ import annotations

from pathlib import Path
from typing import Protocol


class AsrAdapter(Protocol):
    def transcribe(self, wav_path: Path) -> str: ...


class FasterWhisperAdapter:
    """ASR fallback dùng faster-whisper, ép ngôn ngữ tiếng Việt. Model load lười 1 lần."""

    def __init__(self, model_name: str = "large-v3", device: str = "cuda", model: object | None = None) -> None:
        self.model_name = model_name
        self.device = device
        self._model = model

    def _build_model(self):
        from faster_whisper import WhisperModel

        compute_type = "float16" if self.device == "cuda" else "int8"
        try:
            return WhisperModel(self.model_name, device=self.device, compute_type=compute_type)
        except Exception:
            # Không có GPU/driver -> rơi về CPU.
            return WhisperModel(self.model_name, device="cpu", compute_type="int8")

    def _get_model(self):
        if self._model is None:
            self._model = self._build_model()
        return self._model

    def transcribe(self, wav_path: Path) -> str:
        model = self._get_model()
        segments, _info = model.transcribe(str(wav_path), language="vi")
        return " ".join(seg.text.strip() for seg in segments).strip()
