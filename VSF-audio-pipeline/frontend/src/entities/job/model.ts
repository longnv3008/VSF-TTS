export type StepHistoryItem = {
  step: string;
  started_at?: string | null;
  ended_at?: string | null;
  duration_sec?: number | null;
};

export type JobUrl = {
  url: string;
  video_id: string;
  status: string;
  logs_fail?: string | null;
  source_duration_sec?: number | null;
};

export type UrlSummary = {
  total?: number;
  completed?: number;
  failed?: number;
  skipped?: number;
  running?: number;
  queued?: number;
};

export type Job = {
  id: number;
  batch_id: number;
  batch_status: string;
  job_type: string;
  status: string;
  current_step: string;
  batch_name: string;
  manifest_path?: string | null;
  metadata_path?: string | null;
  translation_path?: string | null;
  output_path?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at?: string | null;
  step_history?: StepHistoryItem[];
  urls?: JobUrl[];
  url_summary?: UrlSummary;
  progress_percent?: number;
  progress_label?: string;
};

// Một dòng timing: stage cha khi sub_stage null, hoặc sub-stage (demucs/vad/asr/cut).
export type StageTimingItem = {
  id: number;
  job_id: number;
  batch_id: number;
  video_id: string;
  url?: string | null;
  stage: string;
  sub_stage?: string | null;
  started_at?: string | null;
  ended_at?: string | null;
  duration_sec?: number | null;
  status: string;
};

export type StageAggregate = {
  stage: string;
  sub_stage?: string | null;
  total_duration_sec: number;
  count: number;
  avg_duration_sec: number;
};

export type VideoStageBreakdown = {
  video_id: string;
  url?: string | null;
  stages: StageTimingItem[];
};

export type RunParams = {
  vad_threshold?: number;
  vad_min_volume?: number;
  demucs_enabled?: boolean;
  demucs_model?: string;
  demucs_device?: string;
  asr_model?: string;
};

export type BatchTimingSummary = {
  batch_id: number;
  batch_name: string;
  created_at: string;
  per_stage: StageAggregate[];
  total_duration_sec: number;
  params: RunParams;
};

export type BatchSegment = {
  batch_id: number;
  batch_name: string;
  audio_id: string;
  video_id: string;
  segment_id: string;
  start: number;
  end: number;
  duration: number;
  text: string;
  transcript_source?: string | null;
  transcript_status?: string | null;
  quality_label?: string | null;
  quality_score?: number | null;
  source_url?: string | null;
  title?: string | null;
  audio_url: string;
  audio_available: boolean;
};

export type BatchSegmentPage = {
  items: BatchSegment[];
  total: number;
  offset: number;
  limit: number;
  has_more: boolean;
};
