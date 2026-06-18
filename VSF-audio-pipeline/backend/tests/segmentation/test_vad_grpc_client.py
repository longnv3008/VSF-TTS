from app.modules.audio_pipeline.application.segmentation.types import SegmentationConfig
from app.modules.audio_pipeline.application.segmentation.vad_grpc_client import TritonVadClient


def _cfg() -> SegmentationConfig:
    return SegmentationConfig(
        chunk_ms=64, threshold=0.7, min_volume=0.6, start_secs=0.1, stop_secs=0.45,
        sentence_max_sec=12.0, sentence_min_sec=0.3, phrase_gap_sec=0.45,
        pad_sec=0.1, min_segment_sec=0.3, boundary_slack_sec=0.5, merge_gap_sec=0.5,
    )


class _FakeResult:
    def __init__(self, signals):
        self._signals = signals

    def as_numpy(self, name):
        assert name == "SIGNAL"
        return [str(s).encode("utf-8") for s in self._signals]


class _FakeClient:
    """Trả SPEAKING ở lần infer đầu, QUIET ở lần infer cuối."""

    def __init__(self, url, verbose=False):
        self.calls = 0

    def infer(self, model_name, inputs, sequence_id, sequence_start, sequence_end):
        self.calls += 1
        if sequence_start:
            return _FakeResult([{"signal_type": "SPEAKING", "signal_at": 0.20}])
        if sequence_end:
            return _FakeResult([{"signal_type": "QUIET", "signal_at": 0.90}])
        return _FakeResult([])


def test_detect_regions_builds_region(make_wav):
    wav = make_wav(seconds=1.0)  # 16k -> ~16 chunks of 64ms
    client = TritonVadClient(url="fake:8001", config=_cfg(), client_factory=_FakeClient)
    duration, regions = client.detect_regions(wav)
    assert round(duration, 2) == 1.0
    assert len(regions) == 1
    assert regions[0].start == 0.20 and regions[0].end == 0.90


def test_open_region_closed_at_duration(make_wav):
    wav = make_wav(seconds=1.0)

    class _OnlySpeaking(_FakeClient):
        def infer(self, model_name, inputs, sequence_id, sequence_start, sequence_end):
            if sequence_start:
                return _FakeResult([{"signal_type": "SPEAKING", "signal_at": 0.10}])
            return _FakeResult([])

    client = TritonVadClient(url="fake:8001", config=_cfg(), client_factory=_OnlySpeaking)
    duration, regions = client.detect_regions(wav)
    assert len(regions) == 1
    assert regions[0].start == 0.10
    assert round(regions[0].end, 2) == 1.0
