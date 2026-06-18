// Thứ tự + nhãn 6 stage (khớp backend STEP_ORDER) và sub-stage.
export const STAGE_ORDER = [
  "validate_urls",
  "crawl_audio",
  "vocal_separation",
  "normalize_audio",
  "segment_and_label",
  "build_segment_metadata",
] as const;

export const STAGE_LABELS: Record<string, string> = {
  validate_urls: "Kiểm tra URL",
  crawl_audio: "Tải audio",
  vocal_separation: "Tách giọng (Demucs)",
  normalize_audio: "Chuẩn hóa audio",
  segment_and_label: "Cắt câu & gán nhãn",
  build_segment_metadata: "Ghi metadata",
};

export const SUB_STAGE_LABELS: Record<string, string> = {
  demucs: "Demucs",
  vad: "VAD",
  asr: "ASR",
  cut: "Cắt WAV",
};

export function stageLabel(stage: string): string {
  return STAGE_LABELS[stage] || stage;
}

export function subStageLabel(subStage: string): string {
  return SUB_STAGE_LABELS[subStage] || subStage;
}

export function formatDuration(sec?: number | null): string {
  if (sec == null) return "";
  if (sec < 60) return `${sec.toFixed(1)}s`;
  const m = Math.floor(sec / 60);
  const s = Math.round(sec % 60);
  return `${m}m${s.toString().padStart(2, "0")}s`;
}

// Độ dài video dạng đồng hồ H:MM:SS / M:SS (cho audio gốc).
export function formatClock(sec?: number | null): string {
  if (sec == null) return "";
  const total = Math.round(sec);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const mm = m.toString().padStart(2, "0");
  const ss = s.toString().padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
}

// Giây trôi từ một mốc ISO tới hiện tại (cho timer live).
export function elapsedSince(startedAt?: string | null, now: number = Date.now()): number {
  if (!startedAt) return 0;
  const start = new Date(startedAt).getTime();
  if (Number.isNaN(start)) return 0;
  return Math.max(0, (now - start) / 1000);
}
