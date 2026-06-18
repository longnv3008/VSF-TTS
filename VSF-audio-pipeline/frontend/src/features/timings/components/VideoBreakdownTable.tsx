import { useEffect, useState } from "react";
import { Empty, Table, Tag } from "antd";

import type { StageTimingItem, VideoStageBreakdown } from "../../../entities/job/model";
import { fetchBatchByVideo } from "../../jobs/api/jobs";
import { formatDuration, stageLabel, subStageLabel } from "../stages";

type Props = { batchId: number | null };

export default function VideoBreakdownTable({ batchId }: Props) {
  const [data, setData] = useState<VideoStageBreakdown[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (batchId == null) {
      setData([]);
      return;
    }
    let active = true;
    setLoading(true);
    fetchBatchByVideo(batchId)
      .then((rows) => {
        if (active) setData(rows);
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

  return (
    <Table<VideoStageBreakdown>
      size="small"
      loading={loading}
      rowKey="video_id"
      dataSource={data}
      pagination={false}
      expandable={{
        expandedRowRender: (row) => (
          <Table<StageTimingItem>
            size="small"
            rowKey="id"
            dataSource={row.stages}
            pagination={false}
            columns={[
              { title: "Giai đoạn", dataIndex: "stage", render: (v: string) => stageLabel(v) },
              {
                title: "Sub",
                dataIndex: "sub_stage",
                render: (v: string | null) => (v ? <Tag>{subStageLabel(v)}</Tag> : "—"),
              },
              {
                title: "Thời gian",
                dataIndex: "duration_sec",
                width: 110,
                render: (v: number | null) => formatDuration(v) || "—",
              },
              {
                title: "Trạng thái",
                dataIndex: "status",
                width: 110,
                render: (v: string) => (
                  <Tag color={v === "failed" ? "error" : v === "running" ? "processing" : "success"}>{v}</Tag>
                ),
              },
            ]}
          />
        ),
      }}
      columns={[
        { title: "Video", dataIndex: "video_id", render: (v: string) => v || "(chung)" },
        {
          title: "Tổng thời gian",
          key: "total",
          width: 160,
          render: (_v: unknown, row: VideoStageBreakdown) => {
            const total = row.stages
              .filter((s) => !s.sub_stage)
              .reduce((sum, s) => sum + (s.duration_sec ?? 0), 0);
            return formatDuration(total) || "—";
          },
        },
      ]}
    />
  );
}
