"""Pytest config for scripts/ unit tests.

Adds the ``scripts/`` directory to ``sys.path`` so light, stdlib-only helpers
(e.g. ``_pipeline_common``) are importable without pulling the heavy pipeline
entry-points (which import ``batch_vad`` -> onnxruntime at module load).
"""

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
