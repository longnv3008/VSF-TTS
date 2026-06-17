# VAD Generic Test Suite

Bộ test **model-agnostic** cho VAD module — thiết kế để chạy ổn định khi update audio, model, hoặc tham số.

## Cấu trúc

```
VAD/
├── pytest.ini                          # Config: markers, testpaths, addopts
└── tests/
    ├── __init__.py
    ├── audio_fixtures.py               # Helpers: make_silence/sine/noise/mixed, write_wav, make_vad_args
    ├── conftest.py                     # Pytest fixtures: make_wav_file, silence_wav, vad_args, ...
    ├── test_pure_functions.py          # Unit tests – zero model dependency
    ├── test_vad_session.py             # Unit tests – VADSession state machine
    ├── test_batch_pipeline.py          # Unit tests – read_wav, collect_wav_files, refine pipeline
    └── test_vad_model_integration.py   # Integration tests – full run_vad_file() pipeline
```

## Chạy test

```bash
# Từ thư mục VAD/

# Tất cả (unit + integration, cần ONNX model)
python -m pytest tests/

# Chỉ unit tests (không cần model – nhanh)
python -m pytest tests/ -m "not integration"

# Verbose
python -m pytest tests/ -v

# Chỉ 1 file
python -m pytest tests/test_pure_functions.py -v
```

## Phân loại tests

| File | Marker | Cần model? | Số tests |
|------|--------|------------|----------|
| `test_pure_functions.py` | *(none)* | ❌ | 35 |
| `test_vad_session.py` | *(none)* | ❌ | 14 |
| `test_batch_pipeline.py` | *(none)* | ❌ | 17 |
| `test_vad_model_integration.py` | `integration` | ✅ | 18 (+ 3 parametrized) |

## Thêm test cho audio thực (real WAV files)

Dùng fixture `make_wav_file` trong conftest để tạo WAV synthetic, hoặc đặt file thực vào `tests/data/` và load thẳng:

```python
def test_with_real_audio(vad_model, make_vad_args):
    from pathlib import Path
    import batch_vad as bv
    path = Path("tests/data/my_recording.wav")
    args = make_vad_args()
    duration, segments = bv.run_vad_file(vad_model, path, args)
    assert_structural_invariants(segments, duration)
```

## Invariants được đảm bảo

Mọi output của `run_vad_file()` phải thỏa mãn:
- `label` ∈ `{"speaking", "quiet"}`
- `start < end` cho mỗi segment
- Các segments không overlap, sorted theo thời gian
- `Σ duration ≈ audio_duration` (±0.1s)
- `0 ≤ start`, `end ≤ audio_duration`

## Khi update audio/model

1. Chạy `pytest tests/ -v` → quan sát counts speaking/quiet segments
2. Các **structural invariants luôn phải pass** dù model thay đổi
3. Nếu muốn assert số segment cụ thể, dùng `tests/data/` với ground-truth

## Audio factory

```python
from tests.audio_fixtures import make_mixed, write_wav, make_vad_args

# Tạo audio pattern tùy ý
audio = make_mixed([
    ("silence", 0.5),
    ("speech", 2.0),   # sine wave, loud enough for volume gate
    ("silence", 0.5),
])
```
