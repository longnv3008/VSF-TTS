from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import wave

import numpy as np

from app.modules.audio_pipeline.application.segmentation.types import SegmentationConfig, SpeechRegion


def _normalize_value(value: float, min_value: float, max_value: float) -> float:
    normalized = (value - min_value) / (max_value - min_value)
    return max(0.0, min(1.0, normalized))


def _calculate_audio_volume(audio_np: np.ndarray, sample_rate: int) -> float:
    import pyloudnorm as pyln

    block_size = max(len(audio_np) / sample_rate, 1e-6)
    meter = pyln.Meter(sample_rate, block_size=block_size)
    loudness = meter.integrated_loudness(audio_np.astype(np.float64))
    return _normalize_value(float(loudness), -20.0, 80.0)


def _exp_smoothing(value: float, prev_value: float, factor: float) -> float:
    return prev_value + factor * (value - prev_value)


class VoiceState(Enum):
    QUIET = 1
    STARTING = 2
    SPEAKING = 3
    STOPPING = 4


@dataclass
class VadParams:
    confidence: float = 0.7
    negative_confidence: float | None = None
    start_secs: float = 0.1
    stop_secs: float = 0.45
    min_volume: float = 0.6
    soft_speech: bool = True
    soft_start_confidence_ratio: float = 0.85
    soft_start_volume_ratio: float = 0.85
    soft_start_score: float = 1.85
    soft_continue_confidence_ratio: float = 0.35
    soft_continue_volume_ratio: float = 1.0
    soft_continue_score: float = 1.45


class VadModel:
    def __init__(self, *, model_path: Path, chunk_ms: int = 32, context_ms: int = 4, device: str = "cpu") -> None:
        import onnxruntime

        self._context_ms = context_ms
        self._chunk_ms = chunk_ms
        provider = "CPUExecutionProvider" if device == "cpu" else "CUDAExecutionProvider"
        sess_options = onnxruntime.SessionOptions()
        sess_options.intra_op_num_threads = 1
        self._model = onnxruntime.InferenceSession(str(model_path), sess_options, providers=[provider])

    def detect(
        self,
        batch_data: list[np.ndarray],
        batch_context: np.ndarray,
        batch_state: np.ndarray,
        sample_rate: int,
    ) -> tuple[list[np.ndarray], np.ndarray, np.ndarray]:
        context_size = int(sample_rate * self._context_ms / 1000)
        chunk_size = int(sample_rate * self._chunk_ms / 1000)
        sr = np.array(sample_rate, dtype="int64")

        batch_data_arr = np.array(batch_data, dtype="float32") / 32768.0
        batch_context_arr = np.array(batch_context, dtype="float32")
        batch_state_arr = np.swapaxes(batch_state, 0, 1)

        results: list[np.ndarray] = []
        for i in range(0, batch_data_arr.shape[1], chunk_size):
            data = batch_data_arr[:, i : i + chunk_size]
            data = np.concatenate((batch_context_arr, data), axis=1)
            ort_inputs = {"input": data, "state": batch_state_arr, "sr": sr}
            out, batch_state_arr = self._model.run(None, ort_inputs)
            batch_context_arr = data[:, -context_size:]
            results.append(out)

        return results, batch_state_arr, batch_context_arr


class VadSession:
    def __init__(
        self,
        *,
        param: VadParams,
        context_ms: int = 4,
        chunk_ms: int = 32,
        sample_rate: int = 16000,
    ) -> None:
        self._context_ms = context_ms
        self._chunk_ms = chunk_ms
        self._sample_rate = sample_rate
        self._param = param
        self._total_processed = 0.0
        self._current_processed = 0.0
        self._smoothing_factor = 0.2
        self._prev_volume = 0.0
        self._vad_start_frames = round(self._param.start_secs * 1000 / chunk_ms)
        self._vad_stop_frames = round(self._param.stop_secs * 1000 / chunk_ms)
        self._vad_starting_count = 0
        self._vad_stopping_count = 0
        self._voice_state: VoiceState = VoiceState.QUIET
        self.reset_state()

    def reset_state(self) -> None:
        self._current_processed = 0.0
        context_size = int(self._sample_rate * self._context_ms / 1000)
        self._context = np.zeros((context_size,), dtype="float32")
        self._state = np.zeros((2, 128), dtype="float32")

    def get_state(self) -> tuple[np.ndarray, np.ndarray]:
        return np.copy(self._state), np.copy(self._context)

    def set_state(self, *, state: np.ndarray, context: np.ndarray) -> None:
        self._state = np.copy(state)
        self._context = np.copy(context)

    def is_reset(self, threshold: float = 5.0) -> bool:
        return self._current_processed >= threshold

    def _get_smoothed_volume(self, data: np.ndarray) -> float:
        volume = _calculate_audio_volume(data, self._sample_rate)
        return _exp_smoothing(volume, self._prev_volume, self._smoothing_factor)

    def _is_speaking(self, probability: float, volume: float) -> bool:
        threshold = self._param.confidence
        if self._voice_state in (VoiceState.SPEAKING, VoiceState.STOPPING):
            threshold = self._param.negative_confidence
            if threshold is None:
                threshold = max(self._param.confidence - 0.15, 0.01)

        if probability >= threshold and volume >= self._param.min_volume:
            return True
        if not self._param.soft_speech:
            return False

        confidence_score = probability / max(threshold, 0.01)
        volume_score = volume / max(self._param.min_volume, 0.01)

        if self._voice_state in (VoiceState.SPEAKING, VoiceState.STOPPING):
            return (
                probability >= threshold * self._param.soft_continue_confidence_ratio
                and volume >= self._param.min_volume * self._param.soft_continue_volume_ratio
                and confidence_score + volume_score >= self._param.soft_continue_score
            )

        return (
            probability >= threshold * self._param.soft_start_confidence_ratio
            and volume >= self._param.min_volume * self._param.soft_start_volume_ratio
            and confidence_score + volume_score >= self._param.soft_start_score
        )

    def process(self, data: np.ndarray, probs: np.ndarray) -> list[dict[str, float | str]]:
        self._current_processed += len(data) / self._sample_rate
        chunk_size = int(self._sample_rate * self._chunk_ms / 1000)
        signals: list[dict[str, float | str]] = []

        for idx, probability in enumerate(probs):
            chunk = data[idx * chunk_size : (idx + 1) * chunk_size]
            self._total_processed += len(chunk) / self._sample_rate
            volume = self._get_smoothed_volume(chunk)
            self._prev_volume = volume
            speaking = self._is_speaking(float(probability), volume)

            if speaking:
                if self._voice_state == VoiceState.QUIET:
                    self._voice_state = VoiceState.STARTING
                    self._vad_starting_count = 1
                elif self._voice_state == VoiceState.STARTING:
                    self._vad_starting_count += 1
                elif self._voice_state == VoiceState.STOPPING:
                    self._voice_state = VoiceState.SPEAKING
                    self._vad_stopping_count = 0
            else:
                if self._voice_state == VoiceState.STARTING:
                    self._voice_state = VoiceState.QUIET
                    self._vad_starting_count = 0
                elif self._voice_state == VoiceState.SPEAKING:
                    self._voice_state = VoiceState.STOPPING
                    self._vad_stopping_count = 1
                elif self._voice_state == VoiceState.STOPPING:
                    self._vad_stopping_count += 1

            if self._voice_state == VoiceState.STARTING and self._vad_starting_count >= self._vad_start_frames:
                self._voice_state = VoiceState.SPEAKING
                self._vad_starting_count = 0
                signals.append({"signal_type": VoiceState.SPEAKING.name, "signal_at": max(self._total_processed - self._param.start_secs, 0.0)})

            if self._voice_state == VoiceState.STOPPING and self._vad_stopping_count >= self._vad_stop_frames:
                self._voice_state = VoiceState.QUIET
                self._vad_stopping_count = 0
                signals.append({"signal_type": VoiceState.QUIET.name, "signal_at": max(self._total_processed - self._param.stop_secs, 0.0)})

        return signals


def _default_runtime_factory(*, model_path: Path, config: SegmentationConfig):
    model = VadModel(model_path=model_path, chunk_ms=32, context_ms=4, device="cpu")
    params = VadParams(
        confidence=config.threshold,
        start_secs=config.start_secs,
        stop_secs=config.stop_secs,
        min_volume=config.min_volume,
    )
    return model, params


class OnnxVadClient:
    def __init__(
        self,
        *,
        model_path: Path,
        config: SegmentationConfig,
        runtime_factory=_default_runtime_factory,
    ) -> None:
        self.model_path = model_path
        self.config = config
        self._runtime_factory = runtime_factory

    def detect_regions(self, wav_path: Path) -> tuple[float, list[SpeechRegion]]:
        if not self.model_path.exists():
            raise FileNotFoundError(f"VAD model not found: {self.model_path}")

        model, params = self._runtime_factory(model_path=self.model_path, config=self.config)
        with wave.open(str(wav_path), "rb") as reader:
            sample_rate = reader.getframerate()
            total_frames = reader.getnframes()
            duration = total_frames / sample_rate if sample_rate else 0.0
            frames_per_chunk = max(1, int(self.config.chunk_ms * sample_rate / 1000))
            session = VadSession(
                param=params,
                context_ms=4,
                chunk_ms=32,
                sample_rate=sample_rate,
            )
            regions: list[SpeechRegion] = []
            open_start: float | None = None
            pos = 0

            while pos < total_frames:
                frames = reader.readframes(frames_per_chunk)
                pos += frames_per_chunk
                data = np.frombuffer(frames, dtype=np.int16)
                if data.size < frames_per_chunk:
                    data = np.pad(data, (0, frames_per_chunk - data.size))

                state, context = session.get_state()
                results, next_state, next_context = model.detect([data], np.array([context]), np.array([state]), sample_rate)
                probs = np.concatenate([result[:, 0].flatten() for result in results], axis=0)
                for signal in session.process(data, probs):
                    at = float(signal["signal_at"])
                    if signal["signal_type"] == "SPEAKING" and open_start is None:
                        open_start = at
                    elif signal["signal_type"] == "QUIET" and open_start is not None:
                        regions.append(SpeechRegion(start=open_start, end=at))
                        open_start = None

                if session.is_reset(5):
                    session.reset_state()
                else:
                    session.set_state(state=next_state[:, 0, :], context=next_context[0])

            if open_start is not None:
                regions.append(SpeechRegion(start=open_start, end=duration))

        return duration, regions
