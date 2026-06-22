from app.modules.audio_pipeline.application.exceptions import SkipUrlError
from app.modules.audio_pipeline.application.pipeline_service import AudioPipelineService


class _FakeYoutubeDL:
    def __init__(self, options):
        self.options = options

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def extract_info(self, url, download=True):
        return {
            "id": "vid001",
            "title": "video test",
            "webpage_url": url,
            "duration": 12,
            "requested_downloads": [{"filepath": "/tmp/vid001.webm"}],
        }

    def prepare_filename(self, entry):
        return entry["requested_downloads"][0]["filepath"]


def test_crawl_youtube_skips_url_when_vtt_missing(monkeypatch, tmp_path):
    service = AudioPipelineService()
    telegram_events = []

    raw_file = tmp_path / "vid001.webm"
    raw_file.write_bytes(b"fake-audio")

    monkeypatch.setattr(
        service,
        "_get_ytdlp_modules",
        lambda: (_FakeYoutubeDL, RuntimeError),
    )
    monkeypatch.setattr(service, "_acquire_crawl_slot", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_release_crawl_slot", lambda: None)
    monkeypatch.setattr(service, "_pick_proxy", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_wait_for_proxy_availability", lambda *args, **kwargs: None)
    monkeypatch.setattr(service, "_resolve_audio_file", lambda path: raw_file)
    monkeypatch.setattr(service, "_resolve_subtitle_file", lambda path: None)
    monkeypatch.setattr(service, "_notify_telegram", lambda message, **kwargs: telegram_events.append((message, kwargs)))

    try:
        service.crawl_youtube(["https://youtube.com/watch?v=vid001"], job_id=1, batch_name="b1")
    except SkipUrlError as exc:
        assert exc.failed_url == "https://youtube.com/watch?v=vid001"
        assert "No .vtt subtitle downloaded" in str(exc)
    else:
        raise AssertionError("Expected crawl_youtube to skip URL when .vtt subtitle is missing")

    assert telegram_events
    message, payload = telegram_events[-1]
    assert message == "YouTube subtitle missing"
    assert payload["status"] == "skipped"
    assert payload["reason"] == "missing_vtt"
