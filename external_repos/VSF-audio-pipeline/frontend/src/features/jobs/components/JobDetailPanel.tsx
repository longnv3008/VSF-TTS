import { Empty, Table, Tag } from "antd";
import type { Job, JobUrl, StageTimingItem } from "../../../entities/job/model";
import LiveStageTimeline from "../../timings/components/LiveStageTimeline";
import { formatClock } from "../../timings/stages";

const urlStatusColor: Record<string, string> = {
  queued: "default",
  running: "processing",
  completed: "success",
  skipped: "warning",
  failed: "error",
};

export default function JobDetailPanel({ job, liveTimings }: { job: Job; liveTimings?: StageTimingItem[] }) {
  const urls: JobUrl[] = job.urls ?? [];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: "8px 0" }}>
      <LiveStageTimeline job={job} liveTimings={liveTimings} />

      {urls.length > 0 ? (
        <Table<JobUrl>
          size="small"
          rowKey={(row) => row.url}
          dataSource={urls}
          pagination={false}
          columns={[
            {
              title: "URL",
              dataIndex: "url",
              ellipsis: true,
              render: (value: string) => (
                <a href={value} target="_blank" rel="noreferrer">
                  {value}
                </a>
              ),
            },
            {
              title: "Độ dài",
              dataIndex: "source_duration_sec",
              width: 90,
              align: "right",
              render: (value: number | null) => (value ? formatClock(value) : "—"),
            },
            {
              title: "Trạng thái",
              dataIndex: "status",
              width: 120,
              render: (value: string) => <Tag color={urlStatusColor[value] || "default"}>{value}</Tag>,
            },
            { title: "Lý do (nếu lỗi/skip)", dataIndex: "logs_fail", ellipsis: true },
          ]}
        />
      ) : (
        <Empty description="Chưa có URL" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      )}
    </div>
  );
}
