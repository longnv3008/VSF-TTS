#!/usr/bin/env python
"""Đề xuất reference tự động (DRAFT) bằng map lyric -> segment.

Forced alignment đơn điệu giữa full lyric và chuỗi hypothesis (gộp theo thứ tự segment):
mỗi token lyric gán về segment của token hyp khớp; token lyric không phủ -> carry vào
segment đang xét. Giữ thứ tự + xử điệp khúc lặp. Reference đề xuất = các từ lyric GỐC
thuộc segment đó (ghép lại).

Ghi cột `reference` (DRAFT) + `auto=1` + `match_rate` (độ tin: % token hyp khớp đúng lyric)
vào worksheet. User PHẢI review/sửa — nhất là video hyp rác (match_rate thấp).

Mặc định chỉ xử video CHƯA chấm tay; KHÔNG đụng worksheet đã có reference do người điền.

Chạy:
    python eval/wer/propose_references.py                      # auto: video ref còn trống
    python eval/wer/propose_references.py GGh0dfj2zfY GjSi4OxJORY
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vsf_wer import io_manifest as io  # noqa: E402
from vsf_wer.normalize import normalize  # noqa: E402

_BRACKET_RE = re.compile(r"\[[^\]]*\]")  # nhãn cấu trúc [ĐK:], [âm nhạc] ...
_EDGE_PUNCT_RE = re.compile(r"^\W+|\W+$", re.UNICODE)


def match_key(word: str) -> str:
    """Khóa so khớp: lower + bỏ dấu câu, GIỮ dấu thanh (đồng bộ scorer raw)."""
    return "".join(normalize(word, level="raw").split())


def display(word: str) -> str:
    """Từ hiển thị trong reference: bỏ dấu câu 2 đầu, giữ nguyên chữ + dấu."""
    return _EDGE_PUNCT_RE.sub("", word)


def lyric_tokens(text: str) -> tuple[list[str], list[str]]:
    """(disp, key) song song; bỏ nhãn [..] và token rỗng (vd '*')."""
    disp, key = [], []
    for line in text.splitlines():
        line = _BRACKET_RE.sub(" ", line)
        for w in line.split():
            k = match_key(w)
            if not k:
                continue
            disp.append(display(w))
            key.append(k)
    return disp, key


def hyp_stream(segs) -> tuple[list[str], list[int]]:
    """Chuỗi key hyp gộp theo thứ tự segment + chỉ số segment cho mỗi token."""
    keys, seg_idx = [], []
    for si, s in enumerate(segs):
        for w in s.text.split():
            k = match_key(w)
            if not k:
                continue
            keys.append(k)
            seg_idx.append(si)
    return keys, seg_idx


def forced_align(ref: list[str], hyp: list[str]):
    """NW edit-distance, trả ops (tag, i_ref|None, j_hyp|None). tag M = match/sub."""
    n, m = len(ref), len(hyp)
    d = [[0] * (m + 1) for _ in range(n + 1)]
    bt = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        d[i][0] = i
        bt[i][0] = "D"
    for j in range(1, m + 1):
        d[0][j] = j
        bt[0][j] = "I"
    for i in range(1, n + 1):
        ri = ref[i - 1]
        di, di1 = d[i], d[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ri == hyp[j - 1] else 1
            diag = di1[j - 1] + cost
            up = di1[j] + 1
            left = di[j - 1] + 1
            best = diag if diag <= up and diag <= left else (up if up <= left else left)
            di[j] = best
            bt[i][j] = "M" if best == diag else ("D" if best == up else "I")
    i, j, ops = n, m, []
    while i > 0 or j > 0:
        t = bt[i][j]
        if t == "M":
            ops.append(("M", i - 1, j - 1))
            i, j = i - 1, j - 1
        elif t == "D":
            ops.append(("D", i - 1, None))
            i -= 1
        else:
            ops.append(("I", None, j - 1))
            j -= 1
    ops.reverse()
    return ops


def propose(segs, lyric_disp, lyric_key):
    """-> (refs per segment, match_rate per segment)."""
    hkey, hseg = hyp_stream(segs)
    nseg = len(segs)
    seg_lyric_idx: list[list[int]] = [[] for _ in range(nseg)]
    hyp_total = [0] * nseg
    hyp_hit = [0] * nseg
    for si in hseg:
        hyp_total[si] += 1

    if not hkey:  # không có hyp -> không map được
        return ["" for _ in range(nseg)], [None] * nseg

    ops = forced_align(lyric_key, hkey)
    cur = hseg[0]
    for tag, i, j in ops:
        if tag == "M":
            cur = hseg[j]
            seg_lyric_idx[cur].append(i)
            if lyric_key[i] == hkey[j]:
                hyp_hit[cur] += 1
        elif tag == "I":
            cur = hseg[j]
        else:  # D: lyric token không phủ -> segment hiện tại
            seg_lyric_idx[cur].append(i)

    refs, rates = [], []
    for si in range(nseg):
        idxs = sorted(seg_lyric_idx[si])
        refs.append(" ".join(lyric_disp[i] for i in idxs))
        rates.append(round(hyp_hit[si] / hyp_total[si], 2) if hyp_total[si] else None)
    return refs, rates


def update_worksheet(video_id: str, segs, refs, rates) -> str:
    path = io.WORKSHEETS_DIR / f"{video_id}_worksheet.csv"
    if not path.exists():
        return f"SKIP: chưa có worksheet {path} (chạy build_worksheets.py trước)"
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    filled = sum(1 for r in rows if (r.get("reference") or "").strip())
    if filled:
        return (f"SKIP {video_id}: worksheet đã có {filled} reference điền tay "
                f"— không ghi đè (xóa cột reference nếu muốn auto).")
    by_id = {s.segment_id: k for k, s in enumerate(segs)}
    for r in rows:
        k = by_id.get(r["segment_id"])
        if k is None:
            continue
        r["reference"] = refs[k]
        r["auto"] = "1"
        r["match_rate"] = "" if rates[k] is None else f"{rates[k]:.2f}"
    cols = list(rows[0].keys())
    for c in ("auto", "match_rate"):
        if c not in cols:
            cols.append(c)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    nonempty = sum(1 for k in range(len(segs)) if refs[k])
    avg = [r for r in rates if r is not None]
    avg_rate = sum(avg) / len(avg) if avg else 0
    return (f"WROTE {video_id}: {nonempty}/{len(segs)} segment có ref draft, "
            f"match_rate TB={avg_rate:.2f}")


def main() -> int:
    videos = {v.video_id: v for v in io.load_videos()}
    targets = sys.argv[1:] or None

    by_video = io.load_segments(list(videos))
    chosen = []
    for vid, v in videos.items():
        ws = io.WORKSHEETS_DIR / f"{vid}_worksheet.csv"
        if targets:
            if vid in targets:
                chosen.append(vid)
            continue
        # auto: bỏ qua video đã điền reference tay
        if ws.exists():
            with open(ws, encoding="utf-8-sig", newline="") as f:
                if any((r.get("reference") or "").strip() for r in csv.DictReader(f)):
                    continue
        chosen.append(vid)

    if not chosen:
        print("Không có video nào để đề xuất (đều đã có reference hoặc thiếu worksheet).")
        return 0

    for vid in chosen:
        lyric_path = io.LYRICS_DIR / f"{vid}.txt"
        if not lyric_path.exists():
            print(f"SKIP {vid}: thiếu lyric {lyric_path}")
            continue
        disp, key = lyric_tokens(lyric_path.read_text(encoding="utf-8-sig"))
        refs, rates = propose(by_video.get(vid, []), disp, key)
        print(f"[{vid}] lyric {len(key)} token  →  " + update_worksheet(vid, by_video[vid], refs, rates))

    print("\n⚠️  Đây là DRAFT tự động. Nghe wav_path để SOÁT/SỬA, đặc biệt segment match_rate thấp.")
    print("Xong: python eval/wer/score.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
