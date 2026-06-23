"""Bước 1: chuẩn bị VIVOS (HF datasets) cho fine-tune Whisper.

Tải VIVOS, resample 16kHz, chuẩn hóa transcript target qua normalize_target, lưu ra đĩa
(HF dataset save_to_disk). Heavy deps (datasets, librosa/soundfile) import trong hàm để
module import được trong môi trường pure-unit test.

CLI:
    python prepare_dataset.py --dataset AILAB-VNUHCM/vivos --out-dir data/vivos
"""

from __future__ import annotations

import argparse
from pathlib import Path

from finetune_asr.text_norm import normalize_target

TARGET_SR = 16_000


def _normalize_example(example: dict) -> dict:
    example["target_text"] = normalize_target(example.get("sentence") or example.get("text", ""))
    return example


def prepare(dataset_name: str, out_dir: str, *, split_map: dict[str, str] | None = None) -> None:
    from datasets import Audio, load_dataset

    splits = split_map or {"train": "train", "test": "test"}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for local_name, hf_split in splits.items():
        ds = load_dataset(dataset_name, split=hf_split)
        ds = ds.cast_column("audio", Audio(sampling_rate=TARGET_SR))
        ds = ds.map(_normalize_example)
        ds = ds.filter(lambda e: bool(e["target_text"]))
        ds.save_to_disk(str(out / local_name))
        print(f"saved {local_name}: {len(ds)} examples -> {out / local_name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="AILAB-VNUHCM/vivos")
    ap.add_argument("--out-dir", default="data/vivos")
    args = ap.parse_args()
    prepare(args.dataset, args.out_dir)


if __name__ == "__main__":
    main()
