#!/usr/bin/env python3
import random
import asyncio
import logging
import sounddevice as sd
import argparse
import numpy as np
from ast import literal_eval
import tritonclient.grpc as grpcclient
import uuid

logging.basicConfig(level=logging.INFO)
def int_or_str(text):
    """Helper function for argument parsing."""
    try:
        return int(text)
    except ValueError:
        return text
    
parser = argparse.ArgumentParser()
parser.add_argument('-u', '--uri', type=str, metavar='URL',
                    help='Server URL', default='10.124.68.83:8001')
parser.add_argument('-r', '--sample_rate', type=int, help='sampling rate', default=16000)
parser.add_argument(
        "-d",
        "--device",
        type=int_or_str,
        help="input device (numeric ID or substring)",
    )
args = parser.parse_args()

audio_queue = asyncio.Queue()

sample_rate = args.sample_rate
chunk_ms = 64 # power of 32
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
    
def callback(indata, frames, time, status):
    """This is called (from a separate thread) for each audio block."""
    loop.call_soon_threadsafe(audio_queue.put_nowait, bytes(indata))

async def main():
    global loop
    loop = asyncio.get_running_loop()
    sequence_id = random.randint(1, 100000)  # uniq id
    sess_id = str(uuid.uuid4())
    first = True
    current_ms = 0
    client = grpcclient.InferenceServerClient(url=args.uri)
    input_tensors = None
    try:
        with sd.RawInputStream(
            samplerate=sample_rate,
            blocksize=int(chunk_ms * sample_rate / 1000),
            device=args.device,
            dtype='int16',
            channels=1,
            callback=callback
        ) as device:
            while True:
                chunk = await audio_queue.get()

                current_ms += chunk_ms
                input_tensors = prepare(chunk, sess_id)

                results = client.infer(
                    model_name="vad",
                    inputs=input_tensors,
                    sequence_id=sequence_id,
                    sequence_start=first,
                    sequence_end=False,
                )
                first = False

                signals = results.as_numpy("SIGNAL")
                for signal in signals:
                    signal = literal_eval(signal.decode("utf-8"))
                    print("[{:.2f}] {} at {:.2f}".format(current_ms / 1000, signal["signal_type"], signal["signal_at"]))
    finally:
        if input_tensors is not None and not first:
            client.infer(
                model_name="vad",
                inputs=input_tensors,
                sequence_id=sequence_id,
                sequence_start=False,
                sequence_end=True,
            )

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
