# VAD — Phase 3: Voice Activity Detection

> **Pipeline role:** Phase 3 — nhận `clean_wav/*.wav` (mono 16kHz) → detect speech regions → output cho Phase 4 (label/export).
> **Deep context:** [`docs/phase-03-vad.md`](../docs/phase-03-vad.md)

VAD for detecting speech, segmenting audio and endpointing

### Triton API
- Download and save model to `models/vad/1/vad.onnx`
- Build docker images
```
docker build -f Dockerfile -t vad-server .
```

- Deploy
```
docker run -e TF_CPP_MIN_LOG_LEVEL=1 --shm-size=4096m -e DEBUG=true -d --name vad-server -v ./logs:/logs -it -p8001:8001 vad-server
```

### Testing
- Install client lib: `python>=3.10`
```
pip3 install -r requirements-client.txt
```

- Config
```
sample_rate = 16000
chunk_ms = 64 # power of 32
min_volume = 0.6 # min volume loudness for speech [0,1]
start_secs = 0.3 # min speech duration to decide user start speaking
stop_secs = 0.5 # min silence duration to decide user stop speaking
threshold = 0.7 # VAD model threshold for speech frame [0,1]
```

- Test from file
```sh
python3 client.py 127.0.0.1:8001 audio16k.wav
```

- Test from microphone
```sh
python3 microphone.py -u 127.0.0.1:8001
```

- Output example
```
[0.58] SPEAKING at 0.28
[1.47] QUIET at 0.94

[5.58] SPEAKING at 5.28
[8.47] QUIET at 7.94
```

### Apply VAD module to feed speech segment only into ASR/Encoder
- Target
	+ Filter non-speech audio as ASR/Encoder output trash because of noise
	+ Reduce computational resources as ASR/Encoder run 24/7
- Pseudo code for logic filter [pseudo nonspeechfilter] (pseudo_nonspeech_filter.py)
```
from enum import Enum
from ast import literal_eval
import tritonclient.grpc as grpcclient

class VADState(Enum):
    QUIET = 1
    SPEAKING = 2

# prefix_padding_ms: config in turn_detection realtime api
# start_secs: speech duration to decide user start speaking
max_buffer_size = prefix_padding_ms + start_secs
buffer = b''

current_state = VADState.QUIET
vad = grpcclient.InferenceServerClient()

def get_signal_from_vad(chunk: bytes):
    results = vad.infer(chunk)
    signal = results.as_numpy("SIGNAL")[0]
    signal = literal_eval(signal.decode("utf-8"))

    new_state = None
    if current_state != VADState.SPEAKING and signal["signal_type"] == VADState.SPEAKING.name:
        new_state = VADState.SPEAKING
    
    elif current_state != VADState.QUIET and signal["signal_type"] == VADState.QUIET.name:
        new_state = VADState.QUIET

    return new_state


def main():
    for chunk in recieve_user_record_data():
        reset_asr = False
        data_for_asr = b''
        
        # call VAD to get signal and update state
        # may need to run async
        new_state = get_signal_from_vad(chunk)
        if current_state == VADState.QUIET and new_state == VADState.SPEAKING:
            # user start speaking
            # push audio in buffer for processing downstream (ASR, Encoder)
            # as VAD detect user start speaking only if user's already spoken for start_secs seconds
            data_for_asr += buffer_cache
            buffer_cache = b''
        elif current_state == VADState.SPEAKING and new_state == VADState.QUIET:
            # user stop speaking
            # end request for current sequence-id/callid ASR
            # init new sequence-id/callid for next turn ASR
            # as ASR will be mute after this, so don't need current ASR state for next turn (ASR may be not finalize here)
            # need to reset ASR for better result and don't break flow logic in next turn
            reset_asr = True
        
        if new_state:
            current_state = new_state

        # logic filter non-speech
        if current_state == VADState.QUIET:
            buffer_cache += chunk
            buffer_cache = buffer_cache[-max_buffer_size:]
        elif current_state == VADState.SPEAKING:
            data_for_asr += chunk

        

        # audio bytes to feed to ASR
        yield data_for_asr, reset_asr
```
