#!/usr/bin/env python
"""Chấm WER/CER cho 3 video -> sinh báo cáo + detail CSV.

Hai chế độ:
  - doc-level : gộp toàn bộ label 1 video, so full lyric (data/lyrics/<id>.txt).
  - segment   : từng segment so reference user điền trong worksheet.
Mỗi chế độ báo cả "normalized" (lọc tag+quảng cáo, headline) và "raw" (chỉ
lowercase+bỏ dấu câu) để thấy rác làm phồng WER bao nhiêu.

Chịu được thiếu input: lyric/worksheet nào trống -> đánh dấu "pending", không crash.

Chạy:
    python eval/wer/score.py
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass, field
from datetime import date
from math import isnan
from pathlib import Path

# console Windows (cp1258...) không encode được dấu tiếng Việt -> ép UTF-8, không crash
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vsf_wer import io_manifest as io  # noqa: E402
from vsf_wer import wer as W  # noqa: E402
from vsf_wer.normalize import chars, load_non_lyric, normalize, tokens  # noqa: E402

LEVELS = ("normalized", "raw")

# reference do người chấm ghi để đánh dấu "đoạn không có lời" (nhạc/intro) thay vì để trống
INSTRUMENTAL_SENTINELS = {
    "âm thanh không có lời", "không có lời", "không có lời hát", "không lời",
    "nhạc nền", "nhạc", "instrumental", "im lặng", "không nghe rõ",
}


def fmt_pct(x: float) -> str:
    return "—" if (x is None or isnan(x)) else f"{x * 100:.1f}%"


def norm_ref(text: str, non_lyric, level: str) -> str:
    """Chuẩn hóa reference; nếu là sentinel 'không có lời' -> coi như rỗng (instrumental)."""
    if normalize(text, level="normalized", non_lyric=non_lyric) in INSTRUMENTAL_SENTINELS:
        return ""
    return normalize(text, level=level, non_lyric=non_lyric)


def read_lyric(video_id: str) -> str | None:
    p = io.LYRICS_DIR / f"{video_id}.txt"
    if not p.exists():
        return None
    txt = p.read_text(encoding="utf-8-sig").strip()
    return txt or None


def read_references(video_id: str) -> dict[str, str] | None:
    """Đọc worksheet -> {segment_id: reference}. None nếu chưa có worksheet."""
    p = io.WORKSHEETS_DIR / f"{video_id}_worksheet.csv"
    if not p.exists():
        return None
    refs: dict[str, str] = {}
    with open(p, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            sid = (row.get("segment_id") or "").strip()
            if sid:
                refs[sid] = (row.get("reference") or "").strip()
    return refs


@dataclass
class DocResult:
    wer: dict[str, float] = field(default_factory=dict)   # level -> wer
    cer: dict[str, float] = field(default_factory=dict)
    n_ref: dict[str, int] = field(default_factory=dict)
    counts: dict[str, W.Counts] = field(default_factory=dict)  # level -> token counts
    available: bool = False


@dataclass
class SegResult:
    available: bool = False            # worksheet tồn tại
    has_refs: bool = False             # có ít nhất 1 reference điền
    counts_norm: list[W.Counts] = field(default_factory=list)  # seg có N>0
    counts_raw: list[W.Counts] = field(default_factory=list)
    n_scored: int = 0                  # số seg có reference (kể cả rỗng chủ ý)
    spurious_segs: int = 0             # ref rỗng nhưng hyp có token
    spurious_tokens: int = 0
    total_miss: int = 0                # ref>=3 token nhưng 0 token đúng (label sai hoàn toàn)
    n_with_ref: int = 0                # số seg có ref thực (N>0) -> mẫu số cho total_miss
    sub: int = 0
    dele: int = 0
    ins: int = 0
    examples: list[tuple[str, str]] = field(default_factory=list)  # (segment_id, alignment)


@dataclass
class VideoResult:
    cfg: io.VideoCfg
    n_seg: int
    doc: DocResult
    seg: SegResult


def score_doc(lyric: str | None, segs, non_lyric) -> DocResult:
    r = DocResult()
    if lyric is None:
        return r
    r.available = True
    hyp_text = " ".join(s.text for s in segs)
    for lvl in LEVELS:
        ref_n = normalize(lyric, level=lvl, non_lyric=non_lyric)
        hyp_n = normalize(hyp_text, level=lvl, non_lyric=non_lyric)
        cw = W.align(tokens(ref_n), tokens(hyp_n))
        cc = W.align(chars(ref_n), chars(hyp_n))
        r.wer[lvl] = cw.wer
        r.cer[lvl] = cc.wer
        r.n_ref[lvl] = cw.n_ref
        r.counts[lvl] = cw
    return r


def score_segments(refs: dict[str, str] | None, segs, non_lyric) -> SegResult:
    r = SegResult()
    if refs is None:
        return r
    r.available = True
    scored: list[tuple[str, W.Counts]] = []
    for s in segs:
        ref_text = refs.get(s.segment_id, "")
        if ref_text == "" and s.segment_id not in refs:
            continue  # segment không có dòng trong worksheet
        r.n_scored += 1
        ref_n = norm_ref(ref_text, non_lyric, "normalized")
        hyp_n = normalize(s.text, level="normalized", non_lyric=non_lyric)
        ref_raw = norm_ref(ref_text, non_lyric, "raw")
        hyp_raw = normalize(s.text, level="raw", non_lyric=non_lyric)
        cn = W.align(tokens(ref_n), tokens(hyp_n))
        cr = W.align(tokens(ref_raw), tokens(hyp_raw))
        if ref_text.strip():
            r.has_refs = True
        if cn.n_ref > 0:
            r.counts_norm.append(cn)
            r.counts_raw.append(cr)
            r.sub += cn.sub
            r.dele += cn.dele
            r.ins += cn.ins
            r.n_with_ref += 1
            if cn.n_ref >= 3 and cn.cor == 0:
                r.total_miss += 1   # label sai hoàn toàn (dấu hiệu hallucination)
            scored.append((s.segment_id, cn))
        elif cn.spurious:
            r.spurious_segs += 1
            r.spurious_tokens += cn.ins
    # ví dụ lỗi: 3 segment N>0 lỗi nhiều nhất
    scored.sort(key=lambda x: x[1].errors, reverse=True)
    for sid, c in scored[:3]:
        if c.errors > 0:
            r.examples.append((sid, W.format_alignment(c.ops)))
    return r


def seg_micro(seg: SegResult, level: str) -> float:
    lst = seg.counts_norm if level == "normalized" else seg.counts_raw
    return W.micro_average(lst)


# ----------------------------------------------------------------------------- report

def md_table(headers: list[str], rows: list[list[str]]) -> str:
    line = "| " + " | ".join(headers) + " |"
    sep = "| " + " | ".join("---" for _ in headers) + " |"
    body = "\n".join("| " + " | ".join(r) + " |" for r in rows)
    return "\n".join([line, sep, body])


def build_report(results: list[VideoResult], pending: list[str]) -> str:
    out: list[str] = []
    out.append("# Báo cáo WER — label output 3 video (pipeline E2E)\n")
    out.append(f"_Sinh tự động bởi `eval/wer/score.py` ngày {date.today().isoformat()}._\n")

    # data status
    if pending:
        out.append("> ⚠️ **Thiếu input** (kết quả từng phần):")
        for p in pending:
            out.append(f"> - {p}")
        out.append("")

    # 1. dữ liệu
    out.append("## 1. Dữ liệu\n")
    rows = [
        [r.cfg.video_id, r.cfg.source, str(r.n_seg), r.cfg.title]
        for r in results
    ]
    out.append(md_table(["video_id", "source", "#segment", "title"], rows))
    total = sum(r.n_seg for r in results)
    out.append(f"\nTổng **{total} segment** / {len(results)} video.\n")

    # 2. phương pháp (ngắn)
    out.append("## 2. Phương pháp\n")
    out.append(
        "- **WER** = (S+D+I)/N mức token (âm tiết tách theo space — chuẩn tiếng Việt); "
        "**CER** mức ký tự.\n"
        "- **normalized** (headline): bỏ markup `[..]`/`>>` + cụm non-lyric "
        "(`config/non_lyric.txt`), bỏ dấu câu, lowercase, **giữ dấu thanh**.\n"
        "- **raw**: chỉ lowercase + bỏ dấu câu (giữ rác) — để so độ phồng lỗi.\n"
        "- **doc-level**: gộp toàn bộ label 1 video so full lyric. "
        "**segment**: từng đoạn so reference người nghe điền (micro-average, N>0).\n"
    )

    # 3. doc-level
    out.append("## 3. WER toàn bài (doc-level: label gộp vs full lyric)\n")
    rows = []
    for r in results:
        d = r.doc
        if d.available:
            cn = d.counts.get("normalized")
            sdi = f"S{cn.sub}/D{cn.dele}/I{cn.ins}" if cn else "—"
            rows.append([
                r.cfg.video_id, r.cfg.source, str(d.n_ref.get("normalized", 0)),
                sdi, fmt_pct(d.wer.get("normalized")), fmt_pct(d.cer.get("normalized")),
                fmt_pct(d.wer.get("raw")),
            ])
        else:
            rows.append([r.cfg.video_id, r.cfg.source, "—", "—", "pending", "pending", "pending"])
    out.append(md_table(
        ["video_id", "source", "N_ref", "S/D/I (norm)", "WER (norm)", "CER (norm)",
         "WER (raw)"], rows))
    out.append(
        "\n_D (deletion) cao = label **không phủ hết** lời bài (bỏ đoạn / hát lặp không bắt);"
        " S (substitution) cao = **sai chữ** khi phiên âm. Doc-level trộn cả hai._\n")

    # 4. segment micro
    out.append("## 4. WER theo segment (manual, micro-average)\n")
    rows = []
    for r in results:
        s = r.seg
        if s.available and s.has_refs:
            rows.append([
                r.cfg.video_id, r.cfg.source, str(s.n_scored),
                f"S{s.sub}/D{s.dele}/I{s.ins}",
                fmt_pct(seg_micro(s, "normalized")), fmt_pct(seg_micro(s, "raw")),
                f"{s.total_miss}/{s.n_with_ref}",
                f"{s.spurious_segs} ({s.spurious_tokens} tok)",
            ])
        else:
            rows.append([r.cfg.video_id, r.cfg.source, "—", "—", "pending", "pending",
                         "—", "—"])
    out.append(md_table(
        ["video_id", "source", "#seg chấm", "S/D/I (norm)",
         "WER (norm)", "WER (raw)", "trượt 100%", "spurious"], rows))
    out.append(
        "\n_**trượt 100%** = segment có lời thật nhưng label 0 từ đúng → label sai hoàn toàn"
        " (dấu hiệu ASR hallucination). spurious = lời rỗng nhưng label phát token dư._\n")

    # 5. nhóm vtt vs asr
    out.append("## 5. So sánh nguồn: VTT vs ASR\n")
    rows = []
    for src in ("vtt", "asr"):
        grp = [r for r in results if r.cfg.source == src]
        if not grp:
            continue
        # doc micro: sum errors / sum N qua các video có doc
        doc_err = doc_n = 0
        for r in grp:
            cn = r.doc.counts.get("normalized") if r.doc.available else None
            if cn:
                doc_err += cn.errors
                doc_n += cn.n_ref
        doc_wer = (doc_err / doc_n) if doc_n else float("nan")
        seg_all = [c for r in grp for c in r.seg.counts_norm]
        seg_wer = W.micro_average(seg_all) if seg_all else float("nan")
        rows.append([
            src.upper(), ",".join(r.cfg.video_id for r in grp),
            fmt_pct(doc_wer), fmt_pct(seg_wer),
        ])
    out.append(md_table(["nguồn", "video", "WER doc (norm)", "WER seg (norm)"], rows))
    out.append("")

    # 6. ví dụ lỗi
    out.append("## 6. Ví dụ lỗi điển hình (alignment)\n")
    any_ex = False
    for r in results:
        if r.seg.examples:
            any_ex = True
            out.append(f"### {r.cfg.video_id} ({r.cfg.source})\n")
            for sid, al in r.seg.examples:
                out.append(f"- `{sid}`:\n\n```\n{al}\n```\n")
    if not any_ex:
        out.append("_Chưa có (cần điền reference trong worksheet)._\n")

    # 7. kết luận (auto)
    out.append("## 7. Kết luận (nháp tự động)\n")
    out.extend(auto_conclusions(results))

    return "\n".join(out) + "\n"


def auto_conclusions(results: list[VideoResult]) -> list[str]:
    bullets: list[str] = []
    have_doc = [r for r in results if r.doc.available]
    if not have_doc:
        return ["- Chưa đủ dữ liệu để kết luận (thiếu lyric/worksheet)."]
    for r in have_doc:
        w = r.doc.wer.get("normalized")
        wr = r.doc.wer.get("raw")
        if w is None or isnan(w):
            continue
        cer = r.doc.cer.get("normalized")
        cn = r.doc.counts.get("normalized")
        cause = ""
        if cn and cn.errors:
            if cn.ins > cn.sub and cn.ins > cn.dele:
                cause = " — chủ yếu **dư** (I): label phát text ngoài lời"
            elif cn.dele >= cn.sub and cn.dele >= cn.ins:
                cause = " — chủ yếu **thiếu phủ** (D): label bỏ/không bắt hết lời (lặp, đoạn trống)"
            else:
                cause = " — chủ yếu **sai chữ** (S)"
        # phán định: CER cao = hỏng ký tự thật; D nhiều = coverage, KHÔNG kết tội phiên âm
        if cer is not None and cer > 0.5:
            verdict = "phiên âm hỏng nặng (CER cao)"
        elif cn and cn.dele > cn.sub + cn.ins:
            verdict = "WER cao do thiếu phủ, không phải sai chữ → đo segment để biết chất lượng thật"
        else:
            verdict = "tốt" if w < 0.15 else "khá" if w < 0.35 else "cần xem segment"
        bullets.append(
            f"- **{r.cfg.video_id}** ({r.cfg.source}): WER {fmt_pct(w)} / CER {fmt_pct(cer)} "
            f"(raw WER {fmt_pct(wr)}){cause} → **{verdict}**."
        )
    bullets.append(
        "- ⚠️ Doc-level trộn **chất lượng phiên âm** với **độ phủ** (bài hát lặp điệp khúc "
        "→ D phồng). Verdict chất lượng cuối cùng dựa vào **segment-level** (cần điền worksheet)."
    )
    # vtt vs asr
    def grp_doc_wer(src):
        e = n = 0
        for r in have_doc:
            if r.cfg.source == src:
                cn = r.doc.counts.get("normalized")
                if cn:
                    e += cn.errors
                    n += cn.n_ref
        return (e / n) if n else None
    vtt, asr = grp_doc_wer("vtt"), grp_doc_wer("asr")
    if vtt is not None and asr is not None:
        bullets.append(
            f"- Nhóm doc-WER: VTT {fmt_pct(vtt)} vs ASR {fmt_pct(asr)} — ⚠️ **gây hiểu lầm**, "
            "đừng dùng: gộp video chất lượng trái ngược; chất lượng phụ thuộc **loại caption**, "
            "không phải VTT-vs-ASR."
        )
    # segment-level (chính xác hơn doc-level cho chất lượng)
    for r in results:
        if not r.seg.has_refs:
            continue
        sw = seg_micro(r.seg, "normalized")
        tm, nw = r.seg.total_miss, r.seg.n_with_ref
        note = ""
        if nw and tm / nw >= 0.25:
            note = (f" — ⚠️ **{tm}/{nw} segment sai hoàn toàn** (0 từ đúng): dấu hiệu "
                    "**ASR hallucination** (label = promo/boilerplate thay cho audio thật)")
        elif nw and tm:
            note = f" — {tm}/{nw} segment sai hoàn toàn"
        bullets.append(f"- **{r.cfg.video_id}** (segment): WER {fmt_pct(sw)}{note}.")
    return bullets


# ----------------------------------------------------------------------------- detail csv

def write_detail(video_id: str, segs, refs, non_lyric) -> None:
    io.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = io.REPORTS_DIR / f"wer_detail_{video_id}.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "segment_id", "n_ref", "n_hyp", "S", "D", "I", "C", "wer", "flag",
            "reference_norm", "hypothesis_norm",
        ])
        for s in segs:
            ref_text = (refs or {}).get(s.segment_id, "")
            ref_n = norm_ref(ref_text, non_lyric, "normalized")
            hyp_n = normalize(s.text, level="normalized", non_lyric=non_lyric)
            c = W.align(tokens(ref_n), tokens(hyp_n))
            flag = "spurious" if c.spurious else ("no_ref" if c.n_ref == 0 else "")
            wer_s = "" if isnan(c.wer) else f"{c.wer:.4f}"
            w.writerow([
                s.segment_id, c.n_ref, len(tokens(hyp_n)), c.sub, c.dele, c.ins, c.cor,
                wer_s, flag, ref_n, hyp_n,
            ])


# ----------------------------------------------------------------------------- main

def main() -> int:
    if not io.MANIFEST.exists():
        print(f"LỖI: không thấy manifest {io.MANIFEST}", file=sys.stderr)
        return 1

    non_lyric = load_non_lyric(io.NON_LYRIC_CFG)
    videos = io.load_videos()
    by_video = io.load_segments([v.video_id for v in videos])

    results: list[VideoResult] = []
    pending: list[str] = []

    for v in videos:
        segs = by_video.get(v.video_id, [])
        lyric = read_lyric(v.video_id)
        refs = read_references(v.video_id)

        if lyric is None:
            pending.append(f"Thiếu lyric: `data/lyrics/{v.video_id}.txt` (bỏ qua doc-level).")
        if refs is None:
            pending.append(f"Thiếu worksheet: chạy build_worksheets.py cho `{v.video_id}`.")
        elif not any(refs.values()):
            pending.append(f"Worksheet `{v.video_id}` chưa điền reference (bỏ qua segment).")

        doc = score_doc(lyric, segs, non_lyric)
        seg = score_segments(refs, segs, non_lyric)
        results.append(VideoResult(cfg=v, n_seg=len(segs), doc=doc, seg=seg))

        write_detail(v.video_id, segs, refs, non_lyric)

    io.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = io.REPORTS_DIR / "wer_report.md"
    report_path.write_text(build_report(results, pending), encoding="utf-8")

    # tóm tắt stdout
    print(f"Report: {report_path}")
    for r in results:
        dw = fmt_pct(r.doc.wer.get("normalized")) if r.doc.available else "pending"
        sw = fmt_pct(seg_micro(r.seg, "normalized")) if r.seg.has_refs else "pending"
        print(f"  [{r.cfg.video_id}] {r.cfg.source} seg={r.n_seg:3}  "
              f"doc-WER={dw:>7}  seg-WER={sw:>7}")
    if pending:
        print(f"\n{len(pending)} mục pending (xem đầu report):")
        for p in pending:
            print("  - " + p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
