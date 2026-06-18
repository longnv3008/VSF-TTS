import { useEffect, useState } from "react";
import { Empty, Progress, Table } from "antd";

import type { StageAggregate } from "../../../entities/job/model";
import { fetchBatchAggregate } from "../../jobs/api/jobs";
import { STAGE_ORDER, formatDuration, stageLabel, subStageLabel } from "../stages";

type Props = { batchId: number | null };

type StageRow = {
  key: string;
  stage: string;
  total: number;
  count: number;
  subs: StageAggregate[];
};

export default function StageDurationBars({ batchId }: Props) {
  const [aggregate, setAggregate] = useState<StageAggregate[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (batchId == null) {
      setAggregate([]);
      return;
    }
    let active = true;
    setLoading(true);
    fetchBatchAggregate(batchId)
      .then((rows) => {
        if (active) setAggregate(rows);
      })
      .catch(() => undefined)
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [batchId]);

  if (batchId == null) return <Empty description="Chọn batch" image={Empty.PRESENTED_IMAGE_SIMPLE} />;

  const parents = aggregate.filter((a) => !a.sub_stage);
  const subsByStage = new Map<string, StageAggregate[]>();
  for (const sub of aggregate.filter((a) => a.sub_stage)) {
    const list = subsByStage.get(sub.stage) || [];
    list.push(sub);
    subsByStage.set(sub.stage, list);
  }
  const maxTotal = Math.max(1, ...parents.map((p) => p.total_duration_sec));

  const rows: StageRow[] = STAGE_ORDER.map((stage) => {
    const parent = parents.find((p) => p.stage === stage);
    return {
      key: stage,
      stage,
      total: parent?.total_duration_sec ?? 0,
      count: parent?.count ?? 0,
      subs: subsByStage.get(stage) || [],
    };
  }).filter((row) => row.total > 0 || row.subs.length > 0);

  return (
    <Table<StageRow>
      size="small"
      loading={loading}
      rowKey="key"
      dataSource={rows}
      pagination={false}
      expandable={{
        rowExpandable: (row) => row.subs.length > 0,
        expandedRowRender: (row) => {
          const maxSub = Math.max(1, ...row.subs.map((s) => s.total_duration_sec));
          return (
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {row.subs.map((sub) => (
                <div key={sub.sub_stage} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ width: 90 }}>{subStageLabel(sub.sub_stage || "")}</span>
                  <Progress
                    percent={Math.round((sub.total_duration_sec / maxSub) * 100)}
                    format={() => formatDuration(sub.total_duration_sec)}
                    size="small"
                    style={{ flex: 1 }}
                  />
                </div>
              ))}
            </div>
          );
        },
      }}
      columns={[
        { title: "Giai đoạn", dataIndex: "stage", width: 180, render: (v: string) => stageLabel(v) },
        {
          title: "Tổng thời gian",
          key: "bar",
          render: (_v: unknown, row: StageRow) => (
            <Progress
              percent={Math.round((row.total / maxTotal) * 100)}
              format={() => formatDuration(row.total)}
              size="small"
            />
          ),
        },
        { title: "Số lần", dataIndex: "count", width: 80 },
      ]}
    />
  );
}
