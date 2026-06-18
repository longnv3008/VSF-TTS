from app.core.config import Settings

# Danh sách env vars của segmentation cần clear để test pure defaults (Docker có thể override chúng).
_SEGMENTATION_ENV_VARS = [
    "VAD_GRPC_URL", "VAD_THRESHOLD", "VAD_MIN_VOLUME", "VAD_START_SECS",
    "VAD_STOP_SECS", "VAD_CHUNK_MS", "SEGMENTS_DIR", "SENTENCE_MAX_SEC",
    "SENTENCE_MIN_SEC", "PHRASE_GAP_SEC", "SEGMENT_PAD_SEC",
    "SEGMENT_MIN_SEC", "SEGMENT_BOUNDARY_SLACK_SEC", "SEGMENT_MERGE_GAP_SEC",
    "ASR_MODEL", "ASR_DEVICE",
]


def test_segmentation_settings_defaults(monkeypatch):
    # Clear hết env vars segmentation để kiểm tra giá trị default thực sự.
    for var in _SEGMENTATION_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    s = Settings()
    assert s.vad_grpc_url == "127.0.0.1:8001"
    assert s.vad_threshold == 0.7
    assert s.vad_min_volume == 0.6
    assert s.vad_start_secs == 0.1
    assert s.vad_stop_secs == 0.45
    assert s.segments_dir.as_posix() == "data/processed/segments"
    assert s.sentence_max_sec == 12.0
    assert s.sentence_min_sec == 0.3
    assert s.phrase_gap_sec == 0.45
    assert s.segment_pad_sec == 0.1
    assert s.segment_min_sec == 0.3
    assert s.asr_model == "large-v3"
    assert s.asr_device == "cuda"
