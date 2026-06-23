import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Card, Empty, Input, Select, Space, Statistic, Tag, Typography } from "antd";

import type { BatchSegment } from "../../../entities/job/model";
import { fetchBatchSegments } from "../../jobs/api/jobs";

const API_ROOT = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000/api/v1").replace(/\/api\/v1\/?$/, "");

type ManualWerViewProps = {
  batchOptions: Array<{ value: number; label: string }>;
};

function formatClock(value: number): string {
  if (!Number.isFinite(value)) return "0:00.000";
  const totalMs = Math.max(0, Math.round(value * 1000));
  const minutes = Math.floor(totalMs / 60000);
  const seconds = Math.floor((totalMs % 60000) / 1000);
  const millis = totalMs % 1000;
  return `${minutes}:${seconds.toString().padStart(2, "0")}.${millis.toString().padStart(3, "0")}`;
}

function normalizeText(value: string): string[] {
  return value
    .normalize("NFC")
    .toLocaleLowerCase("vi-VN")
    .replace(/[^\p{L}\p{N}\s]/gu, " ")
    .replace(/\s+/g, " ")
    .trim()
    .split(" ")
    .filter(Boolean);
}

function computeWer(reference: string, hypothesis: string): { distance: number; wordCount: number; ratio: number } {
  const refWords = normalizeText(reference);
  const hypWords = normalizeText(hypothesis);
  if (refWords.length === 0) {
    return {
      distance: hypWords.length,
      wordCount: 0,
      ratio: hypWords.length > 0 ? 1 : 0,
    };
  }

  const rows = refWords.length + 1;
  const cols = hypWords.length + 1;
  const dp: number[][] = Array.from({ length: rows }, () => Array<number>(cols).fill(0));

  for (let i = 0; i < rows; i += 1) dp[i][0] = i;
  for (let j = 0; j < cols; j += 1) dp[0][j] = j;

  for (let i = 1; i < rows; i += 1) {
    for (let j = 1; j < cols; j += 1) {
      const substitutionCost = refWords[i - 1] === hypWords[j - 1] ? 0 : 1;
      dp[i][j] = Math.min(
        dp[i - 1][j] + 1,
        dp[i][j - 1] + 1,
        dp[i - 1][j - 1] + substitutionCost,
      );
    }
  }

  const distance = dp[rows - 1][cols - 1];
  return {
    distance,
    wordCount: refWords.length,
    ratio: distance / refWords.length,
  };
}

export default function ManualWerView({ batchOptions }: ManualWerViewProps) {
  const [batchId, setBatchId] = useState<number | null>(batchOptions[0]?.value ?? null);
  const [segments, setSegments] = useState<BatchSegment[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [manualBySegment, setManualBySegment] = useState<Record<string, string>>({});

  useEffect(() => {
    setBatchId((current) => {
      if (current != null && batchOptions.some((item) => item.value === current)) return current;
      return batchOptions[0]?.value ?? null;
    });
  }, [batchOptions]);

  function loadSegments(nextBatchId: number) {
    setLoading(true);
    setError(null);
    fetchBatchSegments(nextBatchId)
      .then((rows) => {
        setSegments(rows);
        setManualBySegment({});
      })
      .catch((loadError) => {
        setSegments([]);
        setManualBySegment({});
        setError(loadError instanceof Error ? loadError.message : "Khong tai duoc segment cua batch");
      })
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    if (batchId == null) {
      setSegments([]);
      return;
    }
    loadSegments(batchId);
  }, [batchId]);

  const totals = useMemo(() => {
    let totalDistance = 0;
    let totalWords = 0;
    let checkedCount = 0;
    for (const segment of segments) {
      const manualText = manualBySegment[segment.segment_id] ?? "";
      if (!manualText.trim()) continue;
      const wer = computeWer(segment.text, manualText);
      totalDistance += wer.distance;
      totalWords += wer.wordCount;
      checkedCount += 1;
    }
    return {
      checkedCount,
      totalSegments: segments.length,
      ratio: totalWords > 0 ? totalDistance / totalWords : 0,
    };
  }, [manualBySegment, segments]);

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      <Space wrap>
        <Select
          style={{ minWidth: 280 }}
          value={batchId ?? undefined}
          options={batchOptions}
          placeholder="Chọn batch"
          onChange={(value) => setBatchId(value)}
          showSearch
          optionFilterProp="label"
        />
        <Button onClick={() => (batchId != null ? loadSegments(batchId) : undefined)} loading={loading}>
          Refresh
        </Button>
      </Space>

      <Space size={24} wrap>
        <Statistic title="So segment" value={segments.length} />
        <Statistic title="Da check" value={totals.checkedCount} />
        <Statistic title="WER tong" value={Number((totals.ratio * 100).toFixed(2))} suffix="%" />
      </Space>

      {error ? <Alert type="error" showIcon message={error} /> : null}

      {!loading && segments.length === 0 ? <Empty description="Batch này chưa có audio segment để check" /> : null}

      {segments.map((segment) => {
        const manualText = manualBySegment[segment.segment_id] ?? "";
        const wer = computeWer(segment.text, manualText);
        return (
          <Card
            key={segment.segment_id}
            title={segment.segment_id}
            extra={
              <Space size={8} wrap>
                <Tag>{formatClock(segment.start)} - {formatClock(segment.end)}</Tag>
                <Tag color="blue">{segment.duration.toFixed(3)}s</Tag>
                {segment.quality_label ? <Tag color="purple">{segment.quality_label}</Tag> : null}
              </Space>
            }
          >
            <Space direction="vertical" size={12} style={{ width: "100%" }}>
              <Typography.Text type="secondary">
                {segment.title || segment.batch_name}
              </Typography.Text>

              {segment.audio_available ? (
                <audio controls src={`${API_ROOT}${segment.audio_url}`} style={{ width: "100%" }} preload="metadata" />
              ) : (
                <Alert type="warning" showIcon message="Segment này chưa đọc được audio file." />
              )}

              <div>
                <Typography.Text strong>Text batch</Typography.Text>
                <div
                  style={{
                    marginTop: 8,
                    padding: 12,
                    borderRadius: 8,
                    background: "#fafafa",
                    border: "1px solid #f0f0f0",
                    whiteSpace: "pre-wrap",
                  }}
                >
                  {segment.text || "Khong co text"}
                </div>
              </div>

              <Input.TextArea
                rows={4}
                value={manualText}
                onChange={(event) =>
                  setManualBySegment((current) => ({
                    ...current,
                    [segment.segment_id]: event.target.value,
                  }))
                }
                placeholder="Nhap text nghe tay de tinh WER cho segment nay"
              />

              <Space size={24} wrap>
                <Statistic title="WER" value={Number((wer.ratio * 100).toFixed(2))} suffix="%" />
                <Statistic title="Edit Distance" value={wer.distance} />
                <Statistic title="Words Ref" value={wer.wordCount} />
                <Statistic title="Words Nhap Tay" value={normalizeText(manualText).length} />
              </Space>

              {segment.source_url ? (
                <Typography.Link href={segment.source_url} target="_blank" rel="noreferrer">
                  Mở nguồn video
                </Typography.Link>
              ) : null}
            </Space>
          </Card>
        );
      })}
    </Space>
  );
}
