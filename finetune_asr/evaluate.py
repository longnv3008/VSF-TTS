"""Bước 3: eval WER baseline vs fine-tuned (LoRA).

Transcribe tập test + (tùy chọn) domain CSV (audio_path,reference từ manual review 94 seg),
chấm WER micro qua score_wer. Heavy deps import trong hàm.

CLI:
    python evaluate.py --data-dir data/vivos --base openai/whisper-small --adapter ckpt
    python evaluate.py --data-dir data/vivos --adapter ckpt --domain-csv refs.csv
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from finetune_asr.wer_eval import score_wer


def _load_model(base: str, adapter: str | None):
    import torch
    from transformers import WhisperForConditionalGeneration, WhisperProcessor

    processor = WhisperProcessor.from_pretrained(base, language="vi", task="transcribe")
    model = WhisperForConditionalGeneration.from_pretrained(base)
    if adapter:
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, adapter)
    model.eval()
    if torch.cuda.is_available():
        model = model.to("cuda")
    return processor, model


def _transcribe(processor, model, array, sr) -> str:
    import torch

    feats = processor.feature_extractor(array, sampling_rate=sr).input_features[0]
    feats = torch.tensor([feats]).to(model.device)
    with torch.no_grad():
        ids = model.generate(feats, language="vi", task="transcribe")
    return processor.batch_decode(ids, skip_special_tokens=True)[0]


def _eval_split(processor, model, ds) -> float:
    refs, hyps = [], []
    for ex in ds:
        audio = ex["audio"]
        refs.append(ex["target_text"])
        hyps.append(_transcribe(processor, model, audio["array"], audio["sampling_rate"]))
    return score_wer(refs, hyps)


def evaluate(data_dir: str, *, base: str, adapter: str | None, domain_csv: str | None) -> dict:
    from datasets import load_from_disk

    processor, model = _load_model(base, adapter)
    report: dict[str, float] = {}

    test_path = Path(data_dir) / "test"
    if test_path.exists():
        report["vivos_test_wer"] = _eval_split(processor, model, load_from_disk(str(test_path)))

    if domain_csv:
        import soundfile as sf

        refs, hyps = [], []
        with open(domain_csv, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                array, sr = sf.read(row["audio_path"])
                refs.append(row["reference"])
                hyps.append(_transcribe(processor, model, array, sr))
        report["domain_wer"] = score_wer(refs, hyps)

    for k, v in report.items():
        print(f"{k}: {v:.4f}")
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default="data/vivos")
    ap.add_argument("--base", default="openai/whisper-small")
    ap.add_argument("--adapter", default=None, help="LoRA adapter dir; bỏ trống = baseline")
    ap.add_argument("--domain-csv", default=None, help="CSV audio_path,reference (94 human refs)")
    args = ap.parse_args()
    evaluate(args.data_dir, base=args.base, adapter=args.adapter, domain_csv=args.domain_csv)


if __name__ == "__main__":
    main()
