import { useEffect, useMemo, useState } from "react";
import { Alert, Button, Space, Table, Tag } from "antd";
import type { ColumnsType } from "antd/es/table";

import type { BatchTimingSummary } from "../../../entities/job/model";
import { fetchTimingHistory } from "../../jobs/api/jobs";
import { STAGE_ORDER, formatDuration, stageLabel } from "../stages";

function stageTotal(row: BatchTimingSummary, stage: string): number {
  return row.per_stage.find((s) => s.stage === stage)?.total_duration_sec ?? 0;
}

function paramsText(row: BatchTimingSummary): string {
  const p = row.params || {};
  const parts: string[] = [];
  if (p.vad_threshold != null) parts.push(`thr=${p.vad_threshold}`);
  if (p.vad_min_volume != null) parts.push(`vol=${p.vad_min_volume}`);
  if (p.demucs_enabled != null) parts.push(`demucs=${p.demucs_enabled ? "on" : "off"}`);
  return parts.join(" ");
}

function deltaText(after: number, before: number): string {
  const d = after - before;
  const sign = d > 0 ? "+" : "";
  return `${sign}${d.toFixed(1)}s`;
}

export default function HistoryCompareView() {
  const [history, setHistory] = useState<BatchTimingSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<number[]>([]);

  function load() {
    setLoading(true);
    fetchTimingHistory(30)
      .then(setHistory)
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    load();
  }, []);

  const compare = useMemo(() => {
    if (selected.length !== 2) return null;
    const a = history.find((r) => r.batch_id === selected[0]);
    const b = history.find((r) => r.batch_id === selected[1]);
    if (!a || !b) return null;
    // a = run cũ hơn (id nhỏ thường mới hơn, nhưng so theo created_at).
    const [before, after] =
      new Date(a.created_at).getTime() <= new Date(b.created_at).getTime() ? [a, b] : [b, a];
    return { before, after };
  }, [selected, history]);

  const columns: ColumnsType<BatchTimingSummary> = [
    { title: "Batch", dataIndex: "batch_name", fixed: "left", width: 130 },
    {
      title: "Lúc",
      dataIndex: "created_at",
      width: 160,
      render: (v: string) => new Date(v).toLocaleString(),
    },
    ...STAGE_ORDER.map((stage) => ({
      title: stageLabel(stage),
      key: stage,
      width: 120,
      render: (_v: unknown, row: BatchTimingSummary) => formatDuration(stageTotal(row, stage)) || "—",
    })),
    {
      title: "Tổng",
      dataIndex: "total_duration_sec",
      width: 100,
      render: (v: number) => <strong>{formatDuration(v) || "—"}</strong>,
    },
    { title: "Params", key: "params", width: 220, render: (_v: unknown, row) => <Tag>{paramsText(row)}</Tag> },
  ];

  return (
    <Space direction="vertical" size={12} style={{ width: "100%" }}>
      <Space>
        <Button onClick={load} loading={loading}>
          Refresh
        </Button>
        <span style={{ color: "#888" }}>Chọn 2 batch để so sánh delta thời gian.</span>
      </Space>

      {compare ? (
        <Alert
          type="info"
          showIcon
          message={`So sánh: ${compare.before.batch_name} → ${compare.after.batch_name}`}
          description={
            <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
              {STAGE_ORDER.map((stage) => {
                const d = stageTotal(compare.after, stage) - stageTotal(compare.before, stage);
                if (stageTotal(compare.after, stage) === 0 && stageTotal(compare.before, stage) === 0) return null;
                return (
                  <Tag key={stage} color={d < 0 ? "success" : d > 0 ? "error" : "default"}>
                    {stageLabel(stage)}: {deltaText(stageTotal(compare.after, stage), stageTotal(compare.before, stage))}
                  </Tag>
                );
              })}
              <Tag color={compare.after.total_duration_sec < compare.before.total_duration_sec ? "success" : "error"}>
                Tổng: {deltaText(compare.after.total_duration_sec, compare.before.total_duration_sec)}
              </Tag>
            </div>
          }
        />
      ) : null}

      <Table<BatchTimingSummary>
        size="small"
        loading={loading}
        rowKey="batch_id"
        dataSource={history}
        pagination={{ pageSize: 10 }}
        scroll={{ x: 1100 }}
        rowSelection={{
          type: "checkbox",
          selectedRowKeys: selected,
          onChange: (keys) => setSelected((keys as number[]).slice(-2)),
          getCheckboxProps: (row) => ({
            disabled: selected.length >= 2 && !selected.includes(row.batch_id),
          }),
        }}
        columns={columns}
      />
    </Space>
  );
}
