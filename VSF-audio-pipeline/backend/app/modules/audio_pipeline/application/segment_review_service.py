"""Service cho manual WER review: đọc/ghi metadata file, tính WER canonical.

KHÔNG import pipeline_service (kéo audio libs). Chỉ dùng filesystem helpers +
wer_canonical + metadata_fields.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.modules.audio_pipeline.application.segmentation.metadata_fields import (
    SEGMENT_METADATA_FIELDS,
)
from app.modules.audio_pipeline.application.segmentation.wer_canonical import (
    align,
    micro_average,
    normalize,
    tokens,
)
from app.utils.filesystem import write_csv


def _to_float(value: object) -> float | None:
    try:
        text = str(value).strip()
        return float(text) if text else None
    except (TypeError, ValueError):
        return None


class SegmentReviewService:
    def __init__(self, metadata_dir: Path, segments_dir: Path) -> None:
        self.metadata_dir = Path(metadata_dir)
        self.segments_dir = Path(segments_dir)

    # ---- file io ----------------------------------------------------------
    def _jsonl_path(self, batch_name: str) -> Path:
        return self.metadata_dir / f"{batch_name}_segments.jsonl"

    def _csv_path(self, batch_name: str) -> Path:
        return self.metadata_dir / f"{batch_name}_segments.csv"

    def _read_rows(self, batch_name: str) -> list[dict]:
        path = self._jsonl_path(batch_name)
        if not path.exists():
            raise FileNotFoundError(f"Metadata not found for batch: {batch_name}")
        rows: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def _write_rows(self, batch_name: str, rows: list[dict]) -> None:
        normalized = [{k: r.get(k, "") for k in SEGMENT_METADATA_FIELDS} for r in rows]
        with self._jsonl_path(batch_name).open("w", encoding="utf-8") as handle:
            for row in normalized:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        write_csv(self._csv_path(batch_name), SEGMENT_METADATA_FIELDS, normalized)

    # ---- view model -------------------------------------------------------
    def _to_view(self, row: dict) -> dict:
        text = row.get("text", "") or ""
        reference = row.get("reference", "") or ""
        spurious = (not normalize(reference)) and bool(tokens(normalize(text)))
        return {
            "segment_id": row.get("segment_id", ""),
            "text": text,
            "reference": reference,
            "manual_wer": _to_float(row.get("manual_wer")),
            "review_status": row.get("review_status", "") or "pending",
            "start": _to_float(row.get("start")),
            "end": _to_float(row.get("end")),
            "duration": _to_float(row.get("duration")),
            "quality_reasons": row.get("quality_reasons", "") or "",
            "spurious": spurious,
        }

    # ---- public api -------------------------------------------------------
    def list_segments(self, batch_name: str, status: str = "needs_review") -> list[dict]:
        rows = self._read_rows(batch_name)
        return [self._to_view(r) for r in rows if r.get("quality_label") == status]

    def submit_review(self, batch_name: str, segment_id: str, reference: str) -> dict:
        rows = self._read_rows(batch_name)
        target = next((r for r in rows if r.get("segment_id") == segment_id), None)
        if target is None:
            raise FileNotFoundError(f"Segment not found: {segment_id}")

        ref_tokens = tokens(normalize(reference))
        hyp_tokens = tokens(normalize(target.get("text", "")))
        if not ref_tokens:
            target["reference"] = reference
            target["manual_wer"] = ""
            target["review_status"] = "skipped"
        else:
            counts = align(ref_tokens, hyp_tokens)
            target["reference"] = reference
            target["manual_wer"] = f"{counts.wer:.4f}"
            target["review_status"] = "reviewed"

        self._write_rows(batch_name, rows)
        return self._to_view(target)

    def wer_summary(self, batch_name: str) -> dict:
        rows = self._read_rows(batch_name)
        needs = [r for r in rows if r.get("quality_label") == "needs_review"]
        counts_list = []
        reviewed = pending = spurious = 0
        for r in needs:
            status = r.get("review_status", "") or "pending"
            ref_tokens = tokens(normalize(r.get("reference", "")))
            hyp_tokens = tokens(normalize(r.get("text", "")))
            if status == "reviewed" and ref_tokens:
                counts_list.append(align(ref_tokens, hyp_tokens))
                reviewed += 1
            elif status == "skipped":
                if hyp_tokens:
                    spurious += 1
            else:
                pending += 1
        micro = micro_average(counts_list) if counts_list else float("nan")
        return {
            "batch_name": batch_name,
            "micro_wer": None if micro != micro else micro,  # nan -> None
            "reviewed": reviewed,
            "total_needs_review": len(needs),
            "spurious": spurious,
            "pending": pending,
        }

    def resolve_audio_path(self, batch_name: str, segment_id: str) -> Path:
        rows = self._read_rows(batch_name)
        target = next((r for r in rows if r.get("segment_id") == segment_id), None)
        if target is None:
            raise FileNotFoundError(f"Segment not found: {segment_id}")
        raw = target.get("segment_file", "") or ""
        if not raw:
            raise FileNotFoundError(f"No audio path for segment: {segment_id}")
        path = Path(raw).resolve()
        root = self.segments_dir.resolve()
        if root != path and root not in path.parents:
            raise ValueError("Segment file outside segments_dir")
        if not path.exists():
            raise FileNotFoundError(f"Audio file missing: {path}")
        return path
