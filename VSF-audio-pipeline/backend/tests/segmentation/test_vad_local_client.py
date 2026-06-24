from pathlib import Path

from app.modules.audio_pipeline.application.segmentation.types import SegmentationConfig
from app.modules.audio_pipeline.application.segmentation.vad_local_client import OnnxVadClient, VadParams


def _cfg() -> SegmentationConfig:
    return SegmentationConfig(
        chunk_ms=64, threshold=0.7, min_volume=0.6, start_secs=0.1, stop_secs=0.45,
        sentence_max_sec=12.0, sentence_min_sec=0.3, phrase_gap_sec=0.45, use_vtt_transcript=True,
        pad_sec=0.1, min_segment_sec=0.3, boundary_slack_sec=0.5, merge_gap_sec=0.5,
        quality_gate_enabled=False,
    )


class _FakeRuntime:
    def __init__(self):
        self.calls = 0

    def detect(self, batch_data, batch_context, batch_state, sample_rate):
        self.calls += 1
        if self.calls == 1:
            return [__import__("numpy").array([[0.0]])], batch_state.swapaxes(0, 1), batch_context
        return [__import__("numpy").array([[0.0]])], batch_state.swapaxes(0, 1), batch_context


def test_detect_regions_builds_region(make_wav):
    wav = make_wav(seconds=1.0)
    model_path = Path(wav)

    class _SessionRuntime(_FakeRuntime):
        pass

    signals = [
        [{"signal_type": "SPEAKING", "signal_at": 0.20}],
        [],
        [{"signal_type": "QUIET", "signal_at": 0.90}],
    ]

    def _factory(*, model_path, config):
        class _RuntimeWrapper:
            def __init__(self):
                self.calls = 0

            def detect(self, batch_data, batch_context, batch_state, sample_rate):
                import numpy as np

                self.calls += 1
                return [np.array([[0.0]])], batch_state.swapaxes(0, 1), batch_context

        params = VadParams(confidence=config.threshold, start_secs=config.start_secs, stop_secs=config.stop_secs, min_volume=config.min_volume)
        return _RuntimeWrapper(), params

    client = OnnxVadClient(model_path=model_path, config=_cfg(), runtime_factory=_factory)

    import app.modules.audio_pipeline.application.segmentation.vad_local_client as mod

    original_process = mod.VadSession.process
    call_index = {"value": 0}

    def _fake_process(self, data, probs):
        idx = call_index["value"]
        call_index["value"] += 1
        return signals[idx] if idx < len(signals) else []

    mod.VadSession.process = _fake_process
    try:
        duration, regions = client.detect_regions(wav)
    finally:
        mod.VadSession.process = original_process

    assert round(duration, 2) == 1.0
    assert len(regions) == 1
    assert regions[0].start == 0.20 and regions[0].end == 0.90


def test_open_region_closed_at_duration(make_wav):
    wav = make_wav(seconds=1.0)
    model_path = Path(wav)

    def _factory(*, model_path, config):
        import numpy as np

        class _RuntimeWrapper:
            def detect(self, batch_data, batch_context, batch_state, sample_rate):
                return [np.array([[0.0]])], batch_state.swapaxes(0, 1), batch_context

        params = VadParams(confidence=config.threshold, start_secs=config.start_secs, stop_secs=config.stop_secs, min_volume=config.min_volume)
        return _RuntimeWrapper(), params

    client = OnnxVadClient(model_path=model_path, config=_cfg(), runtime_factory=_factory)

    import app.modules.audio_pipeline.application.segmentation.vad_local_client as mod

    original_process = mod.VadSession.process
    fired = {"done": False}

    def _fake_process(self, data, probs):
        if fired["done"]:
            return []
        fired["done"] = True
        return [{"signal_type": "SPEAKING", "signal_at": 0.10}]

    mod.VadSession.process = _fake_process
    try:
        duration, regions = client.detect_regions(wav)
    finally:
        mod.VadSession.process = original_process

    assert len(regions) == 1
    assert regions[0].start == 0.10
    assert round(regions[0].end, 2) == 1.0
