"""Bước 2: fine-tune Whisper bằng LoRA trên dataset đã prepare.

Heavy deps import trong hàm. Lưu LoRA adapter ra --out-dir. --smoke: train 1 step trên
2 sample (verify stack, chạy CPU được).

CLI:
    python train_lora.py --data-dir data/vivos --base openai/whisper-small --out-dir ckpt
    python train_lora.py --data-dir data/vivos --smoke            # smoke CPU
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finetune_asr.lora_config import build_lora_config


@dataclass
class _Collator:
    processor: Any

    def __call__(self, features: list[dict]) -> dict:
        import torch

        input_features = [{"input_features": f["input_features"]} for f in features]
        batch = self.processor.feature_extractor.pad(input_features, return_tensors="pt")
        label_features = [{"input_ids": f["labels"]} for f in features]
        labels_batch = self.processor.tokenizer.pad(label_features, return_tensors="pt")
        labels = labels_batch["input_ids"].masked_fill(labels_batch.attention_mask.ne(1), -100)
        if (labels[:, 0] == self.processor.tokenizer.bos_token_id).all().cpu().item():
            labels = labels[:, 1:]
        batch["labels"] = labels
        return batch


def train(
    data_dir: str,
    out_dir: str,
    *,
    base: str = "openai/whisper-small",
    rank: int = 8,
    lr: float = 1e-4,
    epochs: float = 3.0,
    smoke: bool = False,
    augment: bool = False,
) -> None:
    import numpy as np

    from datasets import load_from_disk
    from peft import get_peft_model
    from transformers import (
        Seq2SeqTrainer,
        Seq2SeqTrainingArguments,
        WhisperForConditionalGeneration,
        WhisperProcessor,
    )

    processor = WhisperProcessor.from_pretrained(base, language="vi", task="transcribe")
    train_ds = load_from_disk(str(Path(data_dir) / "train"))
    if smoke:
        train_ds = train_ds.select(range(min(2, len(train_ds))))

    aug_rng = np.random.default_rng(0)

    def _to_features(batch: dict) -> dict:
        audio = batch["audio"]
        array, sr = audio["array"], audio["sampling_rate"]
        if augment:
            from finetune_asr.augment import apply_waveform_augment

            array = apply_waveform_augment(array, sr, aug_rng)
        feats = processor.feature_extractor(array, sampling_rate=sr).input_features[0]
        if augment:
            from finetune_asr.augment import spec_augment

            feats = spec_augment(feats, rng=aug_rng)
        batch["input_features"] = feats
        batch["labels"] = processor.tokenizer(batch["target_text"]).input_ids
        return batch

    train_ds = train_ds.map(_to_features, remove_columns=train_ds.column_names)

    model = WhisperForConditionalGeneration.from_pretrained(base)
    model.generation_config.language = "vi"
    model.generation_config.task = "transcribe"
    model = get_peft_model(model, build_lora_config(rank=rank))
    model.print_trainable_parameters()

    args = Seq2SeqTrainingArguments(
        output_dir=out_dir,
        per_device_train_batch_size=1 if smoke else 8,
        learning_rate=lr,
        num_train_epochs=epochs,
        max_steps=1 if smoke else -1,
        fp16=not smoke,
        remove_unused_columns=False,
        label_names=["labels"],
        report_to=[],
        logging_steps=1,
    )
    trainer = Seq2SeqTrainer(
        model=model,
        args=args,
        train_dataset=train_ds,
        data_collator=_Collator(processor),
    )
    trainer.train()
    model.save_pretrained(out_dir)
    processor.save_pretrained(out_dir)
    print(f"saved LoRA adapter -> {out_dir}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/vivos")
    ap.add_argument("--out-dir", default="checkpoints/whisper_lora")
    ap.add_argument("--base", default="openai/whisper-small")
    ap.add_argument("--rank", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--epochs", type=float, default=3.0)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--augment", action="store_true")
    args = ap.parse_args()
    train(
        args.data_dir, args.out_dir, base=args.base, rank=args.rank,
        lr=args.lr, epochs=args.epochs, smoke=args.smoke, augment=args.augment,
    )


if __name__ == "__main__":
    main()
