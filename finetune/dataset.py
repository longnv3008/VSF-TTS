"""
dataset.py
==========
PyTorch Dataset cho Silero VAD finetuning.
Load từ file .npz được tạo bởi prepare_dataset.py.

Features:
  - Cân bằng class (oversampling minority class)
  - Augmentation: gain jitter, random noise injection
"""

import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader, WeightedRandomSampler
from pathlib import Path
import sys


SCRIPT_DIR = Path(__file__).resolve().parent

if sys.stdout.encoding != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


class VADDataset(Dataset):
    """
    Dataset cho từng chunk 512 samples (32ms @ 16kHz).

    Args:
        npz_path: Path tới file .npz chứa 'chunks', 'labels', 'sources'
        augment:  Bật augmentation (chỉ dùng cho train set)
        gain_jitter_db: Amplitude jitter ± dB (default ±3dB)
        noise_prob:     Xác suất thêm white noise (default 0.2)
        noise_snr_db:   SNR của noise thêm vào (default 20dB)
    """

    def __init__(
        self,
        npz_path: Path,
        augment: bool = False,
        gain_jitter_db: float = 3.0,
        noise_prob: float = 0.2,
        noise_snr_db: float = 20.0,
    ):
        data = np.load(str(npz_path), allow_pickle=True)
        self.chunks = data["chunks"].astype(np.float32)    # [N, 512]
        self.labels = data["labels"].astype(np.float32)    # [N]
        self.sources = data["sources"]                     # [N] str

        self.augment = augment
        self.gain_jitter_db = gain_jitter_db
        self.noise_prob = noise_prob
        self.noise_snr_db = noise_snr_db

        n_speech = int(self.labels.sum())
        n_silence = len(self.labels) - n_speech
        print(f"[Dataset] Loaded {len(self.labels)} samples từ {npz_path}")
        print(f"  Speech:  {n_speech} ({n_speech/len(self.labels)*100:.1f}%)")
        print(f"  Silence: {n_silence} ({n_silence/len(self.labels)*100:.1f}%)")

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor]:
        chunk = self.chunks[idx].copy()
        label = self.labels[idx]

        if self.augment:
            chunk = self._augment(chunk)

        return torch.from_numpy(chunk), torch.tensor(label, dtype=torch.float32)

    def _augment(self, chunk: np.ndarray) -> np.ndarray:
        """Áp dụng data augmentation."""
        # 1. Gain jitter: nhân với random gain trong khoảng [10^(-db/20), 10^(db/20)]
        gain_db = np.random.uniform(-self.gain_jitter_db, self.gain_jitter_db)
        gain = 10 ** (gain_db / 20.0)
        chunk = chunk * gain

        # 2. Random noise injection
        if np.random.random() < self.noise_prob:
            signal_power = np.mean(chunk ** 2)
            if signal_power > 1e-10:
                noise_power = signal_power / (10 ** (self.noise_snr_db / 10))
                noise = np.random.randn(len(chunk)).astype(np.float32) * np.sqrt(noise_power)
                chunk = chunk + noise

        # 3. Clip để tránh overflow
        chunk = np.clip(chunk, -1.0, 1.0)

        return chunk

    def get_sample_weights(self) -> torch.Tensor:
        """
        Tính trọng số cho WeightedRandomSampler để cân bằng class.
        Trọng số class ngược tỷ lệ với tần suất xuất hiện.
        """
        n_speech = self.labels.sum()
        n_silence = len(self.labels) - n_speech
        n_total = len(self.labels)

        # Weight = n_total / (n_classes * n_samples_in_class)
        w_speech = n_total / (2 * n_speech) if n_speech > 0 else 1.0
        w_silence = n_total / (2 * n_silence) if n_silence > 0 else 1.0

        weights = np.where(self.labels == 1.0, w_speech, w_silence)
        return torch.from_numpy(weights.astype(np.float32))


def create_dataloaders(
    train_npz: Path,
    val_npz: Path,
    batch_size: int = 256,
    num_workers: int = 0,
    balance_classes: bool = True,
) -> tuple[DataLoader, DataLoader]:
    """
    Tạo train và val DataLoader.

    Args:
        balance_classes: Dùng WeightedRandomSampler để cân bằng speech/silence
        num_workers: 0 vì model Silero (nếu dùng JIT) không serialize được
    """
    train_ds = VADDataset(train_npz, augment=True)
    val_ds = VADDataset(val_npz, augment=False)

    if balance_classes:
        sample_weights = train_ds.get_sample_weights()
        sampler = WeightedRandomSampler(
            weights=sample_weights,
            num_samples=len(sample_weights),
            replacement=True,
        )
        train_loader = DataLoader(
            train_ds,
            batch_size=batch_size,
            sampler=sampler,
            num_workers=num_workers,
            pin_memory=True,
        )
    else:
        train_loader = DataLoader(
            train_ds,
            batch_size=batch_size,
            shuffle=True,
            num_workers=num_workers,
            pin_memory=True,
        )

    val_loader = DataLoader(
        val_ds,
        batch_size=batch_size,
        shuffle=False,
        num_workers=num_workers,
        pin_memory=True,
    )

    return train_loader, val_loader


if __name__ == "__main__":
    # Quick test
    import sys
    data_dir = SCRIPT_DIR / "data"
    if not (data_dir / "train.npz").exists():
        print("Chưa có data. Chạy prepare_dataset.py trước.")
        sys.exit(1)

    train_loader, val_loader = create_dataloaders(
        data_dir / "train.npz",
        data_dir / "val.npz",
        batch_size=64,
    )

    chunks, labels = next(iter(train_loader))
    print(f"\nBatch shape: chunks={chunks.shape}, labels={labels.shape}")
    print(f"Label distribution in batch: speech={labels.sum():.0f} silence={(1-labels).sum():.0f}")
    print(f"Chunk value range: [{chunks.min():.3f}, {chunks.max():.3f}]")
