import sys
import time
import random
import numpy as np
from ast import literal_eval
import tritonclient.grpc as grpcclient
import uuid

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")


URL = sys.argv[1]
PATH = sys.argv[2]

sample_rate = 16000
chunk_ms = 64
min_volume = 0.6 # min volume loudness for speech [0,1]
start_secs = 0.1 # min speech duration to decide user start speaking
stop_secs = 0.45 # min silence duration to decide user stop speaking
threshold = 0.7 # VAD model threshold for speech frame [0,1]

def prepare(chunk: bytes, sess_id: str):
    speech_data = np.frombuffer(chunk, dtype=np.int16)
    speech_data = speech_data.astype(np.int16)
    speech_data = speech_data.reshape([1, -1])
    # audio param
    input1 = grpcclient.InferInput("INPUT", speech_data.shape, "INT16")
    input2 = grpcclient.InferInput("SESSION", [1, 1], "BYTES")
    input3 = grpcclient.InferInput("RATE", [1, 1], "INT16")

    # vad param
    input4 = grpcclient.InferInput("THRESHOLD", [1, 1], "FP16")
    input5 = grpcclient.InferInput("VOLUME", [1, 1], "FP16")
    input6 = grpcclient.InferInput("START_SECS", [1, 1], "FP16")
    input7 = grpcclient.InferInput("STOP_SECS", [1, 1], "FP16")

    input_tensors = [input1, input2, input3, input4, input5, input6, input7]
    input_tensors[0].set_data_from_numpy(speech_data.astype(np.int16))
    input_tensors[1].set_data_from_numpy(
        np.array([[f"{sess_id}"]], dtype=np.string_)
    )
    input_tensors[2].set_data_from_numpy(
        np.array([[sample_rate]], dtype=np.int16)
    )
    input_tensors[3].set_data_from_numpy(
        np.array([[threshold]], dtype=np.float16)
    )
    input_tensors[4].set_data_from_numpy(
        np.array([[min_volume]], dtype=np.float16)
    )
    input_tensors[5].set_data_from_numpy(
        np.array([[start_secs]], dtype=np.float16)
    )
    input_tensors[6].set_data_from_numpy(
        np.array([[stop_secs]], dtype=np.float16)
    )
    return input_tensors

def inference(path):
    sequence_id = random.randint(1, 10000)  # uniq id
    sess_id = str(uuid.uuid4())
    print(sequence_id)
    print(sess_id)
    client = grpcclient.InferenceServerClient(url=URL, verbose=False)
    with open(path, "rb") as wf:
        wf.read(44)
        first, end = True, False
        chunk_size = int(chunk_ms * sample_rate * 2 / 1000)
        current_ms = 0
        while not end:
            chunk = wf.read(chunk_size)
            if len(chunk) < chunk_size:
                end = True
                chunk += b"\x00" * (chunk_size - len(chunk))

            current_ms += chunk_ms
            input_tensors = prepare(chunk, sess_id)

            results = client.infer(
                model_name="vad",
                inputs=input_tensors,
                sequence_id=sequence_id,
                sequence_start=first,
                sequence_end=end,
            )
            first = False

            signals = results.as_numpy("SIGNAL")
            for signal in signals:
                signal = literal_eval(signal.decode("utf-8"))
                print("[{:.2f}] {} at {:.2f}".format(current_ms / 1000, signal["signal_type"], signal["signal_at"]))

for i in range(1):
    start = time.time()
    inference(PATH)
    print(f"time: {time.time() - start}")
