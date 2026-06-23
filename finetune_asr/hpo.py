"""Optuna HPO cho LoRA fine-tune: search lr/rank/dropout theo eval WER (minimize).

`suggest_params` thuần (test bằng fake trial). `run_study` import optuna + gọi train/evaluate
(bước GPU thật). Objective trả WER trên VIVOS test (hoặc domain nếu có).

CLI:
    python hpo.py --n-trials 10 --data-dir data/vivos --base openai/whisper-small
"""

from __future__ import annotations

import argparse


def suggest_params(trial) -> dict:
    """Search space: lr (log 1e-5..1e-3), rank in {4,8,16,32}, dropout 0..0.2."""
    return {
        "lr": trial.suggest_float("lr", 1e-5, 1e-3, log=True),
        "rank": trial.suggest_categorical("rank", [4, 8, 16, 32]),
        "dropout": trial.suggest_float("dropout", 0.0, 0.2),
    }


def run_study(
    n_trials: int,
    *,
    data_dir: str = "data/vivos",
    base: str = "openai/whisper-small",
    epochs: float = 1.0,
    augment: bool = False,
):
    import optuna

    from finetune_asr.evaluate import evaluate
    from finetune_asr.train_lora import train

    def objective(trial) -> float:
        p = suggest_params(trial)
        out_dir = f"checkpoints/hpo_trial_{trial.number}"
        train(
            data_dir, out_dir, base=base, rank=p["rank"], lr=p["lr"],
            epochs=epochs, augment=augment,
        )
        report = evaluate(data_dir, base=base, adapter=out_dir, domain_csv=None)
        return report.get("vivos_test_wer", 1.0)

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials)
    print(f"best WER={study.best_value:.4f} params={study.best_params}")
    return study


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-trials", type=int, default=10)
    ap.add_argument("--data-dir", default="data/vivos")
    ap.add_argument("--base", default="openai/whisper-small")
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--augment", action="store_true")
    args = ap.parse_args()
    run_study(args.n_trials, data_dir=args.data_dir, base=args.base,
              epochs=args.epochs, augment=args.augment)


if __name__ == "__main__":
    main()
