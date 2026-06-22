import { useEffect, useState } from "react";
import { Button, Card, Empty, Input, Space, Statistic, Table, Tag, message } from "antd";

import type { ReviewSegment, WerSummary } from "../../../entities/review/model";
import {
  fetchReviewSegments,
  fetchWerSummary,
  segmentAudioUrl,
  submitReview,
} from "../api/review";

type Props = { batchName: string | null };

function werTag(wer: number | null, status: string) {
  if (status === "skipped") return <Tag color="default">skipped</Tag>;
  if (wer === null) return <Tag color="orange">pending</Tag>;
  const pct = (wer * 100).toFixed(1);
  return <Tag color={wer > 0.3 ? "red" : "green"}>{pct}%</Tag>;
}

export default function ReviewPanel({ batchName }: Props) {
  const [segments, setSegments] = useState<ReviewSegment[]>([]);
  const [summary, setSummary] = useState<WerSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [savingId, setSavingId] = useState<string | null>(null);
  const [msgApi, contextHolder] = message.useMessage();

  async function load() {
    if (!batchName) return;
    setLoading(true);
    try {
      const [segs, sum] = await Promise.all([
        fetchReviewSegments(batchName),
        fetchWerSummary(batchName),
      ]);
      setSegments(segs);
      setSummary(sum);
      setDrafts(Object.fromEntries(segs.map((s) => [s.segment_id, s.reference])));
    } catch (error) {
      msgApi.error(error instanceof Error ? error.message : "Không tải được segment review");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batchName]);

  async function handleSave(segmentId: string) {
    if (!batchName) return;
    setSavingId(segmentId);
    try {
      const updated = await submitReview(batchName, segmentId, drafts[segmentId] ?? "");
      setSegments((cur) => cur.map((s) => (s.segment_id === segmentId ? updated : s)));
      setSummary(await fetchWerSummary(batchName));
      msgApi.success("Đã lưu review");
    } catch (error) {
      msgApi.error(error instanceof Error ? error.message : "Lưu review thất bại");
    } finally {
      setSavingId(null);
    }
  }

  if (!batchName) return <Empty description="Chọn batch để review" />;

  const columns = [
    {
      title: "Audio",
      dataIndex: "segment_id",
      width: 240,
      render: (segmentId: string) => (
        // eslint-disable-next-line jsx-a11y/media-has-caption
        <audio controls preload="none" style={{ width: 220 }} src={segmentAudioUrl(batchName, segmentId)} />
      ),
    },
    {
      title: "Label (hypothesis)",
      dataIndex: "text",
      render: (text: string, row: ReviewSegment) => (
        <Space direction="vertical" size={2}>
          <span>{text}</span>
          <Tag color="volcano">{row.quality_reasons}</Tag>
        </Space>
      ),
    },
    {
      title: "Reference (nghe & gõ)",
      dataIndex: "reference",
      width: 280,
      render: (_: string, row: ReviewSegment) => (
        <Input.TextArea
          rows={2}
          value={drafts[row.segment_id] ?? ""}
          placeholder="Lời đúng nghe được (để trống = skip)"
          onChange={(e) =>
            setDrafts((d) => ({ ...d, [row.segment_id]: e.target.value }))
          }
        />
      ),
    },
    {
      title: "WER",
      dataIndex: "manual_wer",
      width: 90,
      render: (wer: number | null, row: ReviewSegment) => werTag(wer, row.review_status),
    },
    {
      title: "",
      width: 90,
      render: (_: unknown, row: ReviewSegment) => (
        <Button
          type="primary"
          size="small"
          loading={savingId === row.segment_id}
          onClick={() => handleSave(row.segment_id)}
        >
          Lưu
        </Button>
      ),
    },
  ];

  return (
    <Space direction="vertical" size={16} style={{ width: "100%" }}>
      {contextHolder}
      {summary && (
        <Card>
          <Space size={48} wrap>
            <Statistic
              title="WER micro (đã review)"
              value={summary.micro_wer === null ? "—" : (summary.micro_wer * 100).toFixed(1)}
              suffix={summary.micro_wer === null ? "" : "%"}
            />
            <Statistic title="Đã review" value={`${summary.reviewed}/${summary.total_needs_review}`} />
            <Statistic title="Pending" value={summary.pending} />
            <Statistic title="Spurious" value={summary.spurious} />
          </Space>
        </Card>
      )}
      <Table
        rowKey="segment_id"
        loading={loading}
        dataSource={segments}
        columns={columns}
        pagination={false}
        size="small"
      />
    </Space>
  );
}
