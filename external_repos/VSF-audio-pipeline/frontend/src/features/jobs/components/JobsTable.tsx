import { Button, Card, Progress, Table, Tag } from "antd";
import type { Job, StageTimingItem } from "../../../entities/job/model";
import JobDetailPanel from "./JobDetailPanel";

const statusColors: Record<string, string> = {
  queued: "default",
  running: "processing",
  completed: "success",
  failed: "error",
  skipped: "warning",
  blocked: "warning",
};

function progressStatus(job: Job): "active" | "success" | "exception" | "normal" {
  if (job.status === "completed") return "success";
  if (job.status === "failed" || job.status === "blocked") return "exception";
  if (job.status === "running") return "active";
  return "normal";
}

type JobsTableProps = {
  jobs: Job[];
  loading: boolean;
  retryingJobId?: number | null;
  timingsByJob?: Record<number, StageTimingItem[]>;
  onRefresh: () => void;
  onRetry: (job: Job) => void;
};

export default function JobsTable({
  jobs,
  loading,
  retryingJobId,
  timingsByJob = {},
  onRefresh,
  onRetry,
}: JobsTableProps) {
  return (
    <Card
      title="Danh sách jobs"
      extra={
        <Button onClick={onRefresh} loading={loading}>
          Refresh
        </Button>
      }
    >
      <Table<Job>
        rowKey="id"
        loading={loading}
        dataSource={jobs}
        pagination={{ pageSize: 5 }}
        scroll={{ x: 900 }}
        expandable={{
          expandedRowRender: (job) => <JobDetailPanel job={job} liveTimings={timingsByJob[job.id]} />,
          rowExpandable: () => true,
        }}
        columns={[
          { title: "ID", dataIndex: "id", width: 70 },
          { title: "Batch", dataIndex: "batch_name" },
          {
            title: "Status",
            dataIndex: "status",
            render: (value: string) => <Tag color={statusColors[value] || "default"}>{value}</Tag>,
          },
          {
            title: "Tiến độ",
            key: "progress",
            width: 200,
            render: (_value: unknown, job: Job) => (
              <div>
                <Progress percent={job.progress_percent ?? 0} size="small" status={progressStatus(job)} />
                <div style={{ fontSize: 12, color: "#888" }}>{job.progress_label || job.current_step}</div>
              </div>
            ),
          },
          { title: "Metadata", dataIndex: "metadata_path", ellipsis: true },
          { title: "Error", dataIndex: "error_message", ellipsis: true },
          {
            title: "Action",
            key: "action",
            width: 140,
            render: (_value: unknown, job: Job) => (
              <Button onClick={() => onRetry(job)} loading={retryingJobId === job.id} disabled={job.status === "running"}>
                Chạy lại
              </Button>
            ),
          },
        ]}
      />
    </Card>
  );
}
