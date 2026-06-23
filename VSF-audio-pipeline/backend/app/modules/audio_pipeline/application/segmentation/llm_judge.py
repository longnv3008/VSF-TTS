"""LLM judge: sửa lỗi chính tả/đồng âm tiếng Việt trên hypothesis ASR cho WER gate.

ASR chỉ là comparator của gate (label vẫn từ VTT). LLM sửa ASR -> WER so VTT gần thật
hơn, bớt flag giả. Opt-in, default OFF (NullJudgeAdapter). Fail-open tuyệt đối: bất kỳ
lỗi mạng/timeout/HTTP nào -> trả text gốc, không bao giờ chặn/vỡ pipeline.
"""

from __future__ import annotations

from typing import Protocol

from app.utils import get_logger

logger = get_logger(__name__)

_PROMPT = (
    "Sửa lỗi chính tả và lỗi đồng âm tiếng Việt trong câu sau. "
    "Giữ nguyên nghĩa, không thêm bớt từ, không giải thích. "
    "Chỉ trả về đúng câu đã sửa:\n\n{text}"
)


class LlmJudgeAdapter(Protocol):
    def correct(self, text: str) -> str: ...


class NullJudgeAdapter:
    """Default khi tắt: trả text nguyên, không gọi mạng."""

    def correct(self, text: str) -> str:
        return text


class OllamaJudgeAdapter:
    """Gọi Ollama /api/generate sửa câu. Lỗi bất kỳ -> trả text gốc (fail-open)."""

    def __init__(
        self,
        *,
        url: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        timeout: float = 30.0,
        client: object | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = client

    def _get_client(self):
        if self._client is None:
            import httpx

            self._client = httpx.Client(timeout=self.timeout)
        return self._client

    def correct(self, text: str) -> str:
        if not text:
            return text
        try:
            resp = self._get_client().post(
                f"{self.url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": _PROMPT.format(text=text),
                    "stream": False,
                    "options": {"temperature": 0.0},
                },
            )
            if getattr(resp, "status_code", 0) != 200:
                logger.warning("llm_judge non-200 (%s); dùng ASR gốc", getattr(resp, "status_code", "?"))
                return text
            out = (resp.json().get("response") or "").strip()
            return out or text
        except Exception as exc:  # fail-open: không bao giờ chặn pipeline
            logger.warning("llm_judge lỗi (%s); dùng ASR gốc", exc)
            return text
