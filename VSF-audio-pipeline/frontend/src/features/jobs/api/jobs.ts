import { apiClient } from "../../../shared/api/client";
import type {
  BatchSegment,
  BatchSegmentPage,
  BatchTimingSummary,
  Job,
  StageAggregate,
  StageTimingItem,
  VideoStageBreakdown,
} from "../../../entities/job/model";

const AUDIO_PIPELINE_BASE_PATH = "/audio-pipeline";
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";

export type JobEvent = {
  type: string;
  job?: Job;
  timing?: StageTimingItem;
};

function toErrorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null) {
    const maybeResponse = error as {
      response?: { data?: { detail?: string } };
      message?: string;
    };
    if (maybeResponse.response?.data?.detail) {
      return maybeResponse.response.data.detail;
    }
    if (maybeResponse.message) {
      return maybeResponse.message;
    }
  }
  return "Unknown API error";
}

export async function fetchJobs(): Promise<Job[]> {
  try {
    const response = await apiClient.get<Job[]>(`${AUDIO_PIPELINE_BASE_PATH}/jobs`);
    return response.data;
  } catch (error) {
    throw new Error(toErrorMessage(error));
  }
}

export async function createIngestJob(payload: { urls: string[]; batch_name: string }): Promise<Job> {
  try {
    const response = await apiClient.post<Job>(`${AUDIO_PIPELINE_BASE_PATH}/jobs/ingest`, payload);
    return response.data;
  } catch (error) {
    throw new Error(toErrorMessage(error));
  }
}

export async function retryJob(jobId: number): Promise<Job> {
  try {
    const response = await apiClient.post<Job>(`${AUDIO_PIPELINE_BASE_PATH}/jobs/${jobId}/retry`);
    return response.data;
  } catch (error) {
    throw new Error(toErrorMessage(error));
  }
}

export function createJobEventsSource(): EventSource {
  return new EventSource(`${API_BASE_URL}${AUDIO_PIPELINE_BASE_PATH}/jobs/events`);
}

export async function fetchJobTimings(jobId: number): Promise<StageTimingItem[]> {
  try {
    const response = await apiClient.get<StageTimingItem[]>(`${AUDIO_PIPELINE_BASE_PATH}/jobs/${jobId}/timings`);
    return response.data;
  } catch (error) {
    throw new Error(toErrorMessage(error));
  }
}

export async function fetchBatchAggregate(batchId: number): Promise<StageAggregate[]> {
  try {
    const response = await apiClient.get<StageAggregate[]>(
      `${AUDIO_PIPELINE_BASE_PATH}/batches/${batchId}/timings/aggregate`,
    );
    return response.data;
  } catch (error) {
    throw new Error(toErrorMessage(error));
  }
}

export async function fetchBatchByVideo(batchId: number): Promise<VideoStageBreakdown[]> {
  try {
    const response = await apiClient.get<VideoStageBreakdown[]>(
      `${AUDIO_PIPELINE_BASE_PATH}/batches/${batchId}/timings/by-video`,
    );
    return response.data;
  } catch (error) {
    throw new Error(toErrorMessage(error));
  }
}

export async function fetchTimingHistory(limit = 20): Promise<BatchTimingSummary[]> {
  try {
    const response = await apiClient.get<BatchTimingSummary[]>(
      `${AUDIO_PIPELINE_BASE_PATH}/timings/history`,
      { params: { limit } },
    );
    return response.data;
  } catch (error) {
    throw new Error(toErrorMessage(error));
  }
}

export async function fetchBatchSegments(
  batchId: number,
  params?: { offset?: number; limit?: number },
): Promise<BatchSegmentPage> {
  try {
    const response = await apiClient.get<BatchSegmentPage>(`${AUDIO_PIPELINE_BASE_PATH}/batches/${batchId}/segments`, {
      params,
    });
    return response.data;
  } catch (error) {
    throw new Error(toErrorMessage(error));
  }
}
