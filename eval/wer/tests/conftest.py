import sys
from pathlib import Path

# cho phép `from vsf_wer import ...` khi chạy pytest từ bất kỳ đâu
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
