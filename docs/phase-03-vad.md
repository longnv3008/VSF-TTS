# Phase 3 — VAD (Voice Activity Detection / Speech Segmentation)

## Role trong pipeline

```
clean_wav/*.wav (mono 16kHz 16-bit)
  → Silero VAD (ONNX) — detect speech regions
  → SpeechRegion list: [{start, end, label}]
  → Phase 4 (Label/export → cut WAV segments)
```

Hai use case:

1. **Offline batch** (`VAD/batch_vad.py`) — dùng trong pipeline, không cần Triton
2. **Real-time streaming** (`VAD/models/vad/` + Triton gRPC) — production turn detection

> [!NOTE]
> VAD engine **thay được** qua seam: Protocol `VadClient` (`segment_service.py:30`,
> "giao diện tối thiểu") + impl cụ thể `vad_local_client.py`. Segmentation phụ thuộc
> interface, nên batch / Triton / VAD khác đều cắm thay được.

## Model

- **Silero VAD v6 ONNX** — `VAD/models/vad/1/vad.onnx`
- Đã xác nhận là bản mới nhất (so sánh byte-for-byte với snakers4/silero-vad master)
- Input: `input [None, None]`, `state [2, None, 128]`, `sr []`
- Output: `output [None, 1]` (speech prob), `stateN [2, None, 128]`

## Tham số production (VAD batch)

```text
threshold        = 0.7    # Ngưỡng confidence Silero [0,1] — cao để tránh false alarm
min_volume       = 0.6    # Ngưỡng âm lượng minimum [0,1]
start_secs       = 0.1    # Speech tối thiểu để trigger SPEAKING
stop_secs        = 0.45   # Silence tối thiểu để trigger QUIET
merge_gap_secs   = 0.5    # Merge các speech region gần nhau
min_speech_secs  = 0.08   # Drop segment quá ngắn
refine_boundaries = True  # Energy-based boundary refinement
```

> [!NOTE]
> Tham số production **cao hơn** code default (`threshold=0.4`, `min_volume=0.3`). Default thấp phù hợp offline test. Production phải override qua CLI.

## State machine (streaming mode)

```
QUIET → STARTING → SPEAKING → STOPPING → QUIET
```

Hysteresis: `negative_confidence` tránh flip-flop ở biên.  
Reset: mỗi 5s để tránh state drift trong session dài.

## VAD batch — offline (dùng trong pipeline)

File: `VAD/batch_vad.py`

```python
from batch_vad import VADModel, run_vad_file

model = VADModel(model_path="VAD/models/vad/1/vad.onnx")
duration, regions = run_vad_file(model, wav_path, args)
# regions: [{"label": "speaking"|"quiet", "start": float, "end": float}]
```

Script test trực tiếp:
```powershell
cd VAD
..\\.venv-vad\Scripts\python batch_vad.py `
  --input-dir ../tmp `
  --output-csv outputs/test_segments.csv `
  --threshold 0.7 --min-volume 0.6
```

## Triton serving — real-time (production)

Docker-based, gRPC port 8001.

```bash
# Build + deploy
docker build -f VAD/Dockerfile -t vad-server VAD/
docker run -e DEBUG=true --shm-size=4096m -d --name vad-server \
  -v ./VAD/logs:/logs -p 8001:8001 vad-server

# Test từ file WAV
python VAD/client.py 127.0.0.1:8001 path/to/audio.wav

# Test từ microphone
python VAD/microphone.py -u 127.0.0.1:8001
```

## Cài environment VAD

```powershell
python -m venv .venv-vad
.venv-vad\Scripts\pip install -r VAD/requirements.txt
```

> [!WARNING]
> **Không cài torch vào `.venv-vad`** — VAD batch dùng onnxruntime, không cần torch. Torch cần cho Demucs (env riêng).

## Known bugs / gotchas (từ project_review.md)

| Mức | Vấn đề | File | Fix |
|---|---|---|---|
| 🔴 | Session leak khi microphone Ctrl+C | `microphone.py` | ✅ Đã fix (signal handler) |
| 🔴 | `KeyError` khi `ready` trước `start` | `model.py:177` | ✅ Đã fix (guard if sess_id not in) |
| 🟡 | `client.py` không đóng file WAV | `client.py:67` | ✅ Đã fix (with statement) |
| 🟡 | Dockerfile base image 22.11 cũ | `Dockerfile` | Chưa fix — upgrade lên 24.x |
| 🟢 | `context` concatenation khác chuẩn Silero | `vad.py:36` | Chưa benchmark |

## Cấu trúc thư mục VAD/

```
VAD/
  batch_vad.py          ← Offline batch pipeline (import từ scripts/)
  models/vad/1/
    vad.onnx            ← Silero V6 model (committed to git)
    model.py            ← Triton Python backend
    vad.py              ← Core VAD logic (VADModel + VADSession)
    utils.py            ← Volume + exponential smoothing
  client.py             ← Test client gRPC
  microphone.py         ← Live mic client
  Dockerfile            ← Triton server container
  requirements.txt      ← VAD env deps (no torch)
  requirements-client.txt
```

## Khi có vấn đề ở phase này

| Triệu chứng | Nguyên nhân | Chỗ fix |
|---|---|---|
| 0 segments output | threshold quá cao, audio quá nhỏ | Hạ `--threshold 0.5`, `--min-volume 0.4` |
| Quá nhiều segments nhỏ | threshold quá thấp | Tăng `--threshold`, tăng `--min-speech-secs` |
| Segment bị cắt sai biên | Boundary refinement issue | Điều chỉnh `--refine-*` params hoặc `--no-refine-boundaries` |
| `onnxruntime` error | Wrong venv hoặc model corrupt | Check `.venv-vad`, verify `vad.onnx` size ~2.3MB |
| Triton container crash | shm-size thiếu hoặc port conflict | Tăng `--shm-size`, check port 8001 |
