from app.modules.audio_pipeline.application.segmentation.llm_judge import (
    NullJudgeAdapter,
    OllamaJudgeAdapter,
)


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _FakeClient:
    """httpx.Client-like: trả resp định trước, hoặc raise nếu exc set."""

    def __init__(self, resp=None, exc=None):
        self._resp, self._exc = resp, exc
        self.calls = 0

    def post(self, *a, **kw):
        self.calls += 1
        if self._exc:
            raise self._exc
        return self._resp


def _judge(client):
    return OllamaJudgeAdapter(url="http://x", model="m", timeout=1.0, client=client)


def test_null_judge_returns_input_unchanged():
    assert NullJudgeAdapter().correct("xin chào các bạn") == "xin chào các bạn"


def test_null_judge_empty():
    assert NullJudgeAdapter().correct("") == ""


def test_ollama_returns_corrected_text():
    client = _FakeClient(resp=_FakeResp(payload={"response": "xin chào các bạn"}))
    assert _judge(client).correct("xin chao cac ban") == "xin chào các bạn"


def test_ollama_fail_open_on_exception():
    client = _FakeClient(exc=RuntimeError("conn refused"))
    assert _judge(client).correct("nguyen ban") == "nguyen ban"
    assert client.calls == 1


def test_ollama_fail_open_on_non_200():
    client = _FakeClient(resp=_FakeResp(status_code=500, payload={}))
    assert _judge(client).correct("nguyen ban") == "nguyen ban"


def test_ollama_empty_input_no_call():
    client = _FakeClient(resp=_FakeResp(payload={"response": "x"}))
    assert _judge(client).correct("") == ""
    assert client.calls == 0
