import numpy as np
from enum import Enum
from typing import Optional
from pydantic import BaseModel
import onnxruntime

from utils import calculate_audio_volume, exp_smoothing

class VADModel:
    def __init__(
        self,
        model_path,
        chunk_ms=32,
        context_ms=4,
        device="cpu",
    ):
        self._context_ms = context_ms
        self._chunk_ms = chunk_ms
        provider = "CPUExecutionProvider" if device == "cpu" else "CUDAExecutionProvider"
        sess_options = onnxruntime.SessionOptions()
        sess_options.intra_op_num_threads = 1
        self._model = onnxruntime.InferenceSession(model_path, sess_options, providers=[provider])

    def detect(self, batch_data, batch_context, batch_state, sr):
        context_size = int(sr * self._context_ms / 1000)
        chunk_size = int(sr * self._chunk_ms / 1000)
        
        sr = np.array(sr, dtype="int64")

        batch_data = np.array(batch_data, dtype="float32") / 32768
        batch_context = np.array(batch_context, dtype="float32")
        batch_state = np.swapaxes(batch_state, 0, 1)
    
        results = []
        for i in range(0, batch_data.shape[1], chunk_size):
            data = batch_data[:, i:i+chunk_size]
            data = np.concatenate((batch_context, data), axis=1)
            
            ort_inputs = {"input": data, "state": batch_state, "sr": sr}
            out, batch_state = self._model.run(None, ort_inputs)
            
            batch_context = data[:, -context_size:]
            results.append(out)

        return results, batch_state, batch_context

class VoiceState(Enum):
    QUIET = 1
    STARTING = 2
    SPEAKING = 3
    STOPPING = 4

class VADParams(BaseModel):
    confidence: float = 0.4
    negative_confidence: Optional[float] = None
    start_secs: float = 0.1
    stop_secs: float = 0.45
    min_volume: float = 0.3
    soft_speech: bool = True
    soft_start_confidence_ratio: float = 0.85
    soft_start_volume_ratio: float = 0.85
    soft_start_score: float = 1.85
    soft_continue_confidence_ratio: float = 0.35
    soft_continue_volume_ratio: float = 1.0
    soft_continue_score: float = 1.45

class VADSession:
    def __init__(
        self,
        param: VADParams,
        context_ms: int = 4,
        chunk_ms: int = 32,
        sample_rate: int = 16000,
    ):
        self._context_ms = context_ms
        self._chunk_ms = chunk_ms
        self._sample_rate = sample_rate
        self._param = param

        self._total_processed = 0
        
        # Volume exponential smoothing
        self._smoothing_factor = 0.2
        self._prev_volume = 0
        

        self._vad_start_frames = round(self._param.start_secs * 1000 / chunk_ms)
        self._vad_stop_frames = round(self._param.stop_secs * 1000 / chunk_ms)
        self._vad_starting_count = 0
        self._vad_stopping_count = 0
        self._voice_state: VoiceState = VoiceState.QUIET
        
        self.reset_state()

    def reset_state(self):
        self._current_processed = 0

        context_size = int(self._sample_rate * self._context_ms / 1000)
        self._context = np.zeros((context_size,), dtype="float32")

        self._state = np.zeros((2, 128), dtype="float32")
    
    def get_state(self):
        return np.copy(self._state), np.copy(self._context)
    
    def set_state(self, state, context):
        self._state = np.copy(state)
        self._context = np.copy(context)
    
    def is_reset(self, threshold=5):
        return self._current_processed >= threshold
    
    def _get_smoothed_volume(self, data) -> float:
        data = data.astype(np.float64)
        volume = calculate_audio_volume(data, self._sample_rate)
        return exp_smoothing(volume, self._prev_volume, self._smoothing_factor)

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
    
    def process(self, data, probs) -> list:
        self._current_processed += len(data) / self._sample_rate

        chunk_size = int(self._sample_rate * self._chunk_ms / 1000)
        signals = []
        for idx, p in enumerate(probs):
            chunk = data[idx * chunk_size : (idx+1) * chunk_size]
            self._total_processed += len(chunk) / self._sample_rate

            volume = self._get_smoothed_volume(chunk)
            self._prev_volume = volume

            speaking = self._is_speaking(p, volume)
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

            if (
                self._voice_state == VoiceState.STARTING
                and self._vad_starting_count >= self._vad_start_frames
            ):
                self._voice_state = VoiceState.SPEAKING
                self._vad_starting_count = 0
                signals.append({
                    "signal_type": VoiceState.SPEAKING.name,
                    "signal_at": max(self._total_processed - self._param.start_secs, 0)
                })
            if (
                self._voice_state == VoiceState.STOPPING
                and self._vad_stopping_count >= self._vad_stop_frames
            ):
                self._voice_state = VoiceState.QUIET
                self._vad_stopping_count = 0
                signals.append({
                    "signal_type": VoiceState.QUIET.name,
                    "signal_at": max(self._total_processed - self._param.stop_secs, 0)
                })
        
        return signals
