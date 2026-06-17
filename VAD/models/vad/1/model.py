import sys
import os
import time
import json
from typing import Dict
import numpy as np
import triton_python_backend_utils as pb_utils
from vad import VADModel, VADSession, VADParams
from loguru import logger

logger.remove(0)
logger.add(sys.stderr, level=os.getenv("LOG_LEVEL", "INFO"))

class TritonPythonModel:
    """Your Python model must use the same class name. Every Python model
    that is created must have "TritonPythonModel" as the class name.
    """

    def initialize(self, args):
        """`initialize` is called only once when the model is being loaded.
        Implementing `initialize` function is optional. This function allows
        the model to initialize any state associated with this model.

        Parameters
        ----------
        args : dict
          Both keys and values are strings. The dictionary keys and values are:
          * model_config: A JSON string containing the model configuration
          * model_instance_kind: A string containing model instance kind
          * model_instance_device_id: A string containing model instance device ID
          * model_repository: Model repository path
          * model_version: Model version
          * model_name: Model name
        """
        self.name = f"vad-{os.getpid()}"
        # You must parse model_config. JSON string is not parsed here
        model_config = json.loads(args["model_config"])

        # Get OUTPUT configuration
        output_config = pb_utils.get_output_config_by_name(model_config, "OUTPUT")

        # Convert Triton types to numpy types
        self.output_dtype = pb_utils.triton_string_to_numpy(
            output_config["data_type"]
        )

        self.config = self.parse_model_params(model_config["parameters"])
        logger.info(f"[{self.name}] config {self.config}")
        
        # Instantiate the PyTorch model
        self.model = VADModel(
            model_path=self.config["model_path"],
            chunk_ms=self.config["chunk_ms"],
            context_ms=self.config["context_ms"],
            device=self.config["device"],
        )
        self.vad_sessions: Dict[str, VADSession] = {}

    def parse_model_params(self, model_params):
        model_p = {
            "chunk_ms": 32,
            "context_ms": 4,
            "model_path": "/models/vad/1/vad.onnx",
            "device": "cpu",
            "reset_duration": 5,
            "threshold": 0.7,
            "start_secs": 0.1,
            "stop_secs": 0.45,
            "min_volume": 0.6,
            "sample_rate": 16000,
        }
        # get parameter configurations
        for li in model_params.items():
            key, value = li
            true_value = value["string_value"]
            if key not in model_p:
                continue
            key_type = type(model_p[key])
            if key_type is None:
                model_p[key] = true_value
            else:
                model_p[key] = key_type(true_value)
        return model_p
    
    def execute(self, requests):
        """`execute` must be implemented in every Python model. `execute`
        function receives a list of pb_utils.InferenceRequest as the only
        argument. This function is called when an inference is requested
        for this model. Depending on the batching configuration (e.g. Dynamic
        Batching) used, `requests` may contain multiple requests. Every
        Python model, must create one pb_utils.InferenceResponse for every
        pb_utils.InferenceRequest in `requests`. If there is an error, you can
        set the error argument when creating a pb_utils.InferenceResponse.

        Parameters
        ----------
        requests : list
          A list of pb_utils.InferenceRequest

        Returns
        -------
        list
          A list of pb_utils.InferenceResponse. The length of this list must
          be the same as `requests`
        """

        batch_data, batch_context, batch_state = [], [], []
        sequence_list, end_of_seq = [], []
        ready_request_indices = []
        sample_rate = None
        # Every Python backend must iterate over everyone of the requests
        # and create a pb_utils.InferenceResponse for each of them.
        for idx, request in enumerate(requests):
            # AUDIO params
            in_0 = pb_utils.get_input_tensor_by_name(request, "INPUT")
            wavs = in_0.as_numpy()[0].astype(np.int16)

            in_1 = pb_utils.get_input_tensor_by_name(request, "SESSION")
            sess_id = in_1.as_numpy()[0][0].decode("utf-8")

            in_2 = pb_utils.get_input_tensor_by_name(request, "RATE")
            sr = in_2.as_numpy()[0][0]
            if not sample_rate:
                sample_rate = sr
            elif sr != sample_rate:
                raise ValueError(f"Got two different sample rate in a batch ({sr}, {sample_rate})")
            if sample_rate != 16000:
                raise ValueError(f"Support sample rate 16000 only, got {sample_rate}")
            
            # VOICE params
            in_cfg = pb_utils.get_input_tensor_by_name(request, "THRESHOLD")
            threshold = in_cfg.as_numpy()[0][0]
            if threshold is None:
                threshold = self.config.get("threshold", 0.7)
            
            in_cfg = pb_utils.get_input_tensor_by_name(request, "VOLUME")
            volume = in_cfg.as_numpy()[0][0]
            if volume is None:
                volume = self.config.get("min_volume", 0.6)
            
            in_cfg = pb_utils.get_input_tensor_by_name(request, "START_SECS")
            start_secs = in_cfg.as_numpy()[0][0]
            if start_secs is None:
                start_secs = self.config.get("start_secs", 0.3)

            in_cfg = pb_utils.get_input_tensor_by_name(request, "STOP_SECS")
            stop_secs = in_cfg.as_numpy()[0][0]
            if stop_secs is None:
                stop_secs = self.config.get("stop_secs", 0.7)
   
            

            # CONTROL params
            in_start = pb_utils.get_input_tensor_by_name(request, "START")
            start = in_start.as_numpy()[0][0]
            
            in_ready = pb_utils.get_input_tensor_by_name(request, "READY")
            ready = in_ready.as_numpy()[0][0]

            in_end = pb_utils.get_input_tensor_by_name(request, "END")
            end = in_end.as_numpy()[0][0]
            

            # Handle request
            if start:
                logger.info(f"[{self.name}] session {sess_id} started")
                self.vad_sessions[sess_id] = VADSession(
                    param=VADParams(
                        confidence=threshold,
                        start_secs=start_secs,
                        stop_secs=stop_secs,
                        min_volume=volume,
                    ),
                    context_ms=self.config["context_ms"],
                    chunk_ms=self.config["chunk_ms"],
                    sample_rate=self.config["sample_rate"],
                )
            if ready:
                if sess_id not in self.vad_sessions:
                    logger.warning(f"[{self.name}] session {sess_id} missing; creating a new session")
                    self.vad_sessions[sess_id] = VADSession(
                        param=VADParams(
                            confidence=threshold,
                            start_secs=start_secs,
                            stop_secs=stop_secs,
                            min_volume=volume,
                        ),
                        context_ms=self.config["context_ms"],
                        chunk_ms=self.config["chunk_ms"],
                        sample_rate=self.config["sample_rate"],
                    )
                state, context = self.vad_sessions[sess_id].get_state()
                batch_data.append(wavs)
                batch_state.append(state)
                batch_context.append(context)
                sequence_list.append(sess_id)
                ready_request_indices.append(idx)
            if end:
                end_of_seq.append(sess_id)

        # batch processing
        responses = [None] * len(requests)
        if sequence_list:
            results, batch_state, batch_context = self.model.detect(batch_data, batch_context, batch_state, sample_rate)
            results = np.array(results, dtype=self.output_dtype)
        
            # hanle results
            for idx, sess_id in enumerate(sequence_list):
                probas = results[:, idx].flatten()

                # get voice signal
                signals = self.vad_sessions[sess_id].process(batch_data[idx], probas)
                if signals:
                    logger.debug(f"[{self.name}] session {sess_id}, signal {signals[0].get('signal_type')} at {signals[0].get('signal_at'):.02f}")

                # update state
                if self.vad_sessions[sess_id].is_reset(self.config["reset_duration"]):
                    self.vad_sessions[sess_id].reset_state()
                else:
                    self.vad_sessions[sess_id].set_state(
                        state=batch_state[:, idx, :],
                        context=batch_context[idx],
                    )

                proba_tensor = pb_utils.Tensor("OUTPUT", probas)
            
                signals = np.array(signals)
                signal_tensor = pb_utils.Tensor("SIGNAL", signals.astype(pb_utils.triton_string_to_numpy("TYPE_STRING")))
                inference_response = pb_utils.InferenceResponse(
                    output_tensors=[proba_tensor, signal_tensor]
                )
                responses[ready_request_indices[idx]] = inference_response

        # cleanup
        for sess_id in end_of_seq:
            if sess_id in self.vad_sessions:
                del self.vad_sessions[sess_id]
                logger.info(f"[{self.name}] session {sess_id} removed")

        for idx, response in enumerate(responses):
            if response is None:
                proba_tensor = pb_utils.Tensor("OUTPUT", np.array([], dtype=self.output_dtype))
                signal_tensor = pb_utils.Tensor(
                    "SIGNAL",
                    np.array([], dtype=pb_utils.triton_string_to_numpy("TYPE_STRING")),
                )
                responses[idx] = pb_utils.InferenceResponse(
                    output_tensors=[proba_tensor, signal_tensor]
                )

        # You should return a list of pb_utils.InferenceResponse. Length
        # of this list must match the length of `requests` list.
        return responses

    def finalize(self):
        """`finalize` is called only once when the model is being unloaded.
        Implementing `finalize` function is optional. This function allows
        the model to perform any necessary clean ups before exit.
        """
        logger.info(f"[{self.name}] Cleaning up...")
