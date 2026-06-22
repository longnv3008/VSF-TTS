import { apiClient } from "../../../shared/api/client";
import type { ReviewSegment, WerSummary } from "../../../entities/review/model";

const BASE = "/audio-pipeline";
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1";

function toErrorMessage(error: unknown): string {
  if (typeof error === "object" && error !== null) {
    const e = error as { response?: { data?: { detail?: string } }; message?: string };
    if (e.response?.data?.detail) return e.response.data.detail;
    if (e.message) return e.message;
  }
  return "Unknown API error";
}

export async function fetchReviewSegments(batchName: string): Promise<ReviewSegment[]> {
  try {
    const res = await apiClient.get<ReviewSegment[]>(
      `${BASE}/batches/${encodeURIComponent(batchName)}/segments`,
      { params: { status: "needs_review" } },
    );
    return res.data;
  } catch (error) {
    throw new Error(toErrorMessage(error));
  }
}

export async function submitReview(
  batchName: string,
  segmentId: string,
  reference: string,
): Promise<ReviewSegment> {
  try {
    const res = await apiClient.post<ReviewSegment>(
      `${BASE}/batches/${encodeURIComponent(batchName)}/segments/${encodeURIComponent(segmentId)}/review`,
      { reference },
    );
    return res.data;
  } catch (error) {
    throw new Error(toErrorMessage(error));
  }
}

export async function fetchWerSummary(batchName: string): Promise<WerSummary> {
  try {
    const res = await apiClient.get<WerSummary>(
      `${BASE}/batches/${encodeURIComponent(batchName)}/wer-summary`,
    );
    return res.data;
  } catch (error) {
    throw new Error(toErrorMessage(error));
  }
}

export function segmentAudioUrl(batchName: string, segmentId: string): string {
  return `${API_BASE_URL}${BASE}/batches/${encodeURIComponent(batchName)}/segments/${encodeURIComponent(segmentId)}/audio`;
}
