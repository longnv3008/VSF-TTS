from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.modules.audio_pipeline.application.segmentation.text_quality import clean_transcript


class AsrAdapter(Protocol):
    def transcribe(self, wav_path: Path) -> str: ...


class FasterWhisperAdapter:
    """ASR fallback dùng faster-whisper, ép tiếng Việt + decode hardening chống ảo giác.

    Decode params nghiêm ngặt (greedy, không điều kiện ngữ cảnh, gate no_speech) triệt tiêu
    hành vi tự sinh chữ khi gặp khoảng lặng/nhiễu. Hậu xử lý `clean_transcript` loại tiếp
    phân đoạn no_speech cao + logprob thấp, cụm blocklist, vòng lặp; rồi chuẩn hóa VLSP.
    Model load lười 1 lần.
    """

    def __init__(
        self,
        model_name: str = "large-v3",
        device: str = "cuda",
        model: object | None = None,
        *,
        beam_size: int = 5,
        no_speech_threshold: float = 0.6,
        logprob_min: float = -1.0,
        vad_filter: bool = True,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self._model = model
        self.beam_size = beam_size
        self.no_speech_threshold = no_speech_threshold
        self.logprob_min = logprob_min
        self.vad_filter = vad_filter

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

    def _decode_kwargs(self) -> dict:
        # Beam search nhỏ giúp bám sát accent tốt hơn greedy, vẫn giữ temperature 0 để
        # tránh lan truyền ảo giác giữa các phân đoạn. vad_filter = lớp gate Silero nội bộ phụ.
        return {
            "language": "vi",
            "beam_size": self.beam_size,
            "temperature": 0.0,
            "condition_on_previous_text": False,
            "no_speech_threshold": self.no_speech_threshold,
            "log_prob_threshold": self.logprob_min,
            "vad_filter": self.vad_filter,
        }

    def transcribe(self, wav_path: Path) -> str:
        model = self._get_model()
        segments, _info = model.transcribe(str(wav_path), **self._decode_kwargs())
        seg_list = list(segments)
        if not seg_list:
            return ""
        text = " ".join(seg.text.strip() for seg in seg_list).strip()
        # no_speech: lấy max (phân đoạn giống lặng nhất); logprob: trung bình các phân đoạn.
        no_speech_prob = max((getattr(seg, "no_speech_prob", 0.0) or 0.0) for seg in seg_list)
        logprobs = [(getattr(seg, "avg_logprob", 0.0) or 0.0) for seg in seg_list]
        avg_logprob = sum(logprobs) / len(logprobs)
        return clean_transcript(
            text,
            no_speech_prob=no_speech_prob,
            avg_logprob=avg_logprob,
            no_speech_max=self.no_speech_threshold,
            logprob_min=self.logprob_min,
        )
