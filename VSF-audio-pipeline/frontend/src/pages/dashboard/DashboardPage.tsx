import { useEffect, useMemo, useState } from "react";
import { Alert, Col, Row, Select, Space, Tabs, message } from "antd";

import type { Job, StageTimingItem } from "../../entities/job/model";
import { createIngestJob, createJobEventsSource, fetchJobs, retryJob, type JobEvent } from "../../features/jobs/api/jobs";
import CreateJobForm, { type CreateJobValues } from "../../features/jobs/components/CreateJobForm";
import JobsTable from "../../features/jobs/components/JobsTable";
import JobSummaryCards from "../../features/jobs/components/JobSummaryCards";
import HistoryCompareView from "../../features/timings/components/HistoryCompareView";
import StageDurationBars from "../../features/timings/components/StageDurationBars";
import VideoBreakdownTable from "../../features/timings/components/VideoBreakdownTable";

function upsertJob(jobs: Job[], nextJob: Job): Job[] {
  const nextJobs = [...jobs];
  const index = nextJobs.findIndex((job) => job.id === nextJob.id);
  if (index >= 0) {
    nextJobs[index] = nextJob;
  } else {
    nextJobs.unshift(nextJob);
  }
  return nextJobs.sort((left, right) => right.id - left.id);
}

function upsertTiming(
  byJob: Record<number, StageTimingItem[]>,
  timing: StageTimingItem,
): Record<number, StageTimingItem[]> {
  const list = byJob[timing.job_id] ? [...byJob[timing.job_id]] : [];
  const index = list.findIndex((item) => item.id === timing.id);
  if (index >= 0) list[index] = timing;
  else list.push(timing);
  return { ...byJob, [timing.job_id]: list };
}

export default function DashboardPage() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [timingsByJob, setTimingsByJob] = useState<Record<number, StageTimingItem[]>>({});
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [retryingJobId, setRetryingJobId] = useState<number | null>(null);
  const [selectedBatchId, setSelectedBatchId] = useState<number | null>(null);
  const [msgApi, contextHolder] = message.useMessage();

  async function loadJobs() {
    setLoading(true);
    try {
      setJobs(await fetchJobs());
    } catch (error) {
      msgApi.error(error instanceof Error ? error.message : "Khong tai duoc danh sach jobs");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadJobs();
    const eventSource = createJobEventsSource();
    eventSource.addEventListener("job", (event) => {
      const payload = JSON.parse((event as MessageEvent<string>).data) as JobEvent;
      if (payload.type === "stage_timing" && payload.timing) {
        const timing = payload.timing;
        setTimingsByJob((current) => upsertTiming(current, timing));
        return;
      }
      if (payload.job) {
        const job = payload.job;
        setJobs((currentJobs) => upsertJob(currentJobs, job));
      }
    });
    eventSource.onerror = () => {
      eventSource.close();
    };
    return () => eventSource.close();
  }, []);

  // Danh sách batch (unique) để chọn trong tab Aggregate / By-video.
  const batchOptions = useMemo(() => {
    const seen = new Map<number, string>();
    for (const job of jobs) {
      if (!seen.has(job.batch_id)) seen.set(job.batch_id, job.batch_name);
    }
    return [...seen.entries()].map(([id, name]) => ({ value: id, label: `#${id} · ${name}` }));
  }, [jobs]);

  async function handleCreateJob(values: CreateJobValues) {
    const urls = values.urls
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean);

    setSubmitting(true);
    try {
      const job = await createIngestJob({
        batch_name: values.batch_name,
        urls,
      });
      setJobs((currentJobs) => upsertJob(currentJobs, job));
      msgApi.success("Da tao ingest job");
    } catch (error) {
      msgApi.error(error instanceof Error ? error.message : "Tao job that bai");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRetryJob(job: Job) {
    setRetryingJobId(job.id);
    try {
      const retriedJob = await retryJob(job.id);
      setJobs((currentJobs) => upsertJob(currentJobs, retriedJob));
      msgApi.success(`Da tao job chay lai cho batch ${job.batch_name}`);
    } catch (error) {
      msgApi.error(error instanceof Error ? error.message : "Chay lai batch that bai");
    } finally {
      setRetryingJobId(null);
    }
  }

  const batchPicker = (
    <Select
      style={{ minWidth: 240, marginBottom: 12 }}
      placeholder="Chọn batch"
      options={batchOptions}
      value={selectedBatchId ?? undefined}
      onChange={(value) => setSelectedBatchId(value)}
      allowClear
    />
  );

  const liveTab = (
    <Row gutter={[16, 16]}>
      <Col xs={24} lg={10}>
        <CreateJobForm loading={submitting} onSubmit={handleCreateJob} />
      </Col>
      <Col xs={24} lg={14}>
        <JobsTable
          jobs={jobs}
          loading={loading}
          retryingJobId={retryingJobId}
          timingsByJob={timingsByJob}
          onRefresh={loadJobs}
          onRetry={handleRetryJob}
        />
      </Col>
    </Row>
  );

  return (
    <Space direction="vertical" size={24} style={{ width: "100%" }}>
      {contextHolder}
      <Alert
        type="info"
        showIcon
        message="Theo dõi pipeline theo từng giai đoạn"
        description="Live = từng stage chạy + thời gian thực. Aggregate/By-video = bottleneck mỗi batch. History = so sánh thời gian giữa các run khi đổi param."
      />

      <JobSummaryCards jobs={jobs} />

      <Tabs
        defaultActiveKey="live"
        items={[
          { key: "live", label: "Live", children: liveTab },
          {
            key: "aggregate",
            label: "Tổng theo stage",
            children: (
              <div>
                {batchPicker}
                <StageDurationBars batchId={selectedBatchId} />
              </div>
            ),
          },
          {
            key: "by-video",
            label: "Theo video",
            children: (
              <div>
                {batchPicker}
                <VideoBreakdownTable batchId={selectedBatchId} />
              </div>
            ),
          },
          { key: "history", label: "Lịch sử / So sánh", children: <HistoryCompareView /> },
        ]}
      />
    </Space>
  );
}
