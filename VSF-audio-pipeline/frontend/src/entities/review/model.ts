export type ReviewSegment = {
  segment_id: string;
  text: string;
  reference: string;
  manual_wer: number | null;
  review_status: string;
  start: number | null;
  end: number | null;
  duration: number | null;
  quality_reasons: string;
  spurious: boolean;
};

export type WerSummary = {
  batch_name: string;
  micro_wer: number | null;
  reviewed: number;
  total_needs_review: number;
  spurious: number;
  pending: number;
};
