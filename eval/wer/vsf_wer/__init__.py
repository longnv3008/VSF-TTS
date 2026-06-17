"""vsf_wer — bộ đo WER/CER cho label output pipeline TTS (pure-Python, stdlib).

Modules:
    normalize   chuẩn hóa text + lọc cụm non-lyric
    wer         Levenshtein mức token, đếm S/D/I/C/N, alignment, CER, micro-average
    io_manifest đọc manifest batch_001, lọc video target, sửa đường WAV
"""

__all__ = ["normalize", "wer", "io_manifest"]
