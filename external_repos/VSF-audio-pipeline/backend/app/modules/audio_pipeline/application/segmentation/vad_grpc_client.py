from __future__ import annotations

import random
import uuid
import wave
from ast import literal_eval
from pathlib import Path
from typing import Callable

import numpy as np

from app.modules.audio_pipeline.application.segmentation.types import SegmentationConfig, SpeechRegion


def _default_client_factory(url: str, verbose: bool = False):
    # Lazy-import để API startup không cần tritonclient.
    import tritonclient.grpc as grpcclient

    return grpcclient.InferenceServerClient(url=url, verbose=verbose)


class TritonVadClient:
    def __init__(
        self,
        url: str,
        config: SegmentationConfig,
        client_factory: Callable[..., object] = _default_client_factory,
    ) -> None:
        self.url = url
        self.config = config
        self._client_factory = client_factory

    def _build_inputs(self, data: np.ndarray, sess_id: str, sample_rate: int) -> list:
        import tritonclient.grpc as grpcclient

        data = data.astype(np.int16).reshape([1, -1])
        in_audio = grpcclient.InferInput("INPUT", data.shape, "INT16")
        in_sess = grpcclient.InferInput("SESSION", [1, 1], "BYTES")
        in_rate = grpcclient.InferInput("RATE", [1, 1], "INT16")
        in_thr = grpcclient.InferInput("THRESHOLD", [1, 1], "FP16")
        in_vol = grpcclient.InferInput("VOLUME", [1, 1], "FP16")
        in_start = grpcclient.InferInput("START_SECS", [1, 1], "FP16")
        in_stop = grpcclient.InferInput("STOP_SECS", [1, 1], "FP16")

        in_audio.set_data_from_numpy(data)
        in_sess.set_data_from_numpy(np.array([[f"{sess_id}"]], dtype=np.bytes_))
        in_rate.set_data_from_numpy(np.array([[sample_rate]], dtype=np.int16))
        in_thr.set_data_from_numpy(np.array([[self.config.threshold]], dtype=np.float16))
        in_vol.set_data_from_numpy(np.array([[self.config.min_volume]], dtype=np.float16))
        in_start.set_data_from_numpy(np.array([[self.config.start_secs]], dtype=np.float16))
        in_stop.set_data_from_numpy(np.array([[self.config.stop_secs]], dtype=np.float16))
        return [in_audio, in_sess, in_rate, in_thr, in_vol, in_start, in_stop]

    def detect_regions(self, wav_path: Path) -> tuple[float, list[SpeechRegion]]:
        with wave.open(str(wav_path), "rb") as reader:
            sample_rate = reader.getframerate()
            total_frames = reader.getnframes()
            duration = total_frames / sample_rate if sample_rate else 0.0
            frames_per_chunk = max(1, int(self.config.chunk_ms * sample_rate / 1000))

            client = self._client_factory(url=self.url, verbose=False)
            seq_id = random.randint(1, 1_000_000)
            sess_id = str(uuid.uuid4())
            first = True
            regions: list[SpeechRegion] = []
            open_start: float | None = None
            pos = 0

            while pos < total_frames:
                frames = reader.readframes(frames_per_chunk)
                pos += frames_per_chunk
                end = pos >= total_frames
                data = np.frombuffer(frames, dtype=np.int16)
                if data.size < frames_per_chunk:
                    data = np.pad(data, (0, frames_per_chunk - data.size))

                inputs = self._build_inputs(data, sess_id, sample_rate)
                result = client.infer(
                    model_name="vad",
                    inputs=inputs,
                    sequence_id=seq_id,
                    sequence_start=first,
                    sequence_end=end,
                )
                first = False
                for raw in result.as_numpy("SIGNAL"):
                    payload = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                    signal = literal_eval(payload)
                    at = float(signal["signal_at"])
                    if signal["signal_type"] == "SPEAKING" and open_start is None:
                        open_start = at
                    elif signal["signal_type"] == "QUIET" and open_start is not None:
                        regions.append(SpeechRegion(start=open_start, end=at))
                        open_start = None

            if open_start is not None:
                regions.append(SpeechRegion(start=open_start, end=duration))

        return duration, regions
