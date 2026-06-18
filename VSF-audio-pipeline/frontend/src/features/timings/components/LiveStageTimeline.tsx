import { useEffect, useMemo, useState } from "react";
import { Empty, Steps, Tag } from "antd";

import type { Job, StageTimingItem } from "../../../entities/job/model";
import { fetchJobTimings } from "../../jobs/api/jobs";
import { STAGE_ORDER, elapsedSince, formatDuration, stageLabel, subStageLabel } from "../stages";

type Props = {
  job: Job;
  liveTimings?: StageTimingItem[];
};

function mergeById(base: StageTimingItem[], live: StageTimingItem[]): StageTimingItem[] {
  const byId = new Map<number, StageTimingItem>();
  for (const item of base) byId.set(item.id, item);
  for (const item of live) byId.set(item.id, item);
  return [...byId.values()].sort((a, b) => a.id - b.id);
}

function durationText(item: StageTimingItem | undefined, now: number): string {
  if (!item) return "";
  if (item.duration_sec != null) return formatDuration(item.duration_sec);
  if (item.status === "running") return `${elapsedSince(item.started_at, now).toFixed(1)}s…`;
  return "";
}

export default function LiveStageTimeline({ job, liveTimings = [] }: Props) {
  const [fetched, setFetched] = useState<StageTimingItem[]>([]);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    let active = true;
    fetchJobTimings(job.id)
      .then((rows) => {
        if (active) setFetched(rows);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
    // Refetch khi job đổi trạng thái kết thúc (chốt duration cuối).
  }, [job.id, job.status]);

  // Tick mỗi giây khi job đang chạy để timer live nhảy số.
  useEffect(() => {
    if (job.status !== "running") return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [job.status]);

  const merged = useMemo(() => mergeById(fetched, liveTimings), [fetched, liveTimings]);

  const items = STAGE_ORDER.map((stage) => {
    const parent = merged.find((t) => t.stage === stage && !t.sub_stage);
    const subs = merged.filter((t) => t.stage === stage && t.sub_stage);

    let status: "wait" | "process" | "finish" | "error" = "wait";
    if (parent?.status === "failed") status = "error";
    else if (parent?.duration_sec != null || parent?.status === "completed") status = "finish";
    else if (parent?.status === "running") status = "process";
    else if (job.current_step === stage) status = "process";
    else if (job.status === "completed") status = "finish";

    const parentDur = durationText(parent, now);
    const description = (
      <div style={{ fontSize: 12 }}>
        {parentDur ? <span style={{ color: "#555" }}>{parentDur}</span> : null}
        {subs.length > 0 ? (
          <div style={{ marginTop: 4, display: "flex", flexWrap: "wrap", gap: 4 }}>
            {subs.map((sub) => (
              <Tag
                key={sub.id}
                color={sub.status === "failed" ? "error" : sub.status === "running" ? "processing" : "blue"}
                style={{ margin: 0 }}
              >
                {subStageLabel(sub.sub_stage || "")}: {durationText(sub, now) || "—"}
              </Tag>
            ))}
          </div>
        ) : null}
      </div>
    );

    return { title: stageLabel(stage), status, description };
  });

  if (merged.length === 0 && job.status === "queued") {
    return <Empty description="Chưa chạy" image={Empty.PRESENTED_IMAGE_SIMPLE} />;
  }

  return <Steps direction="vertical" size="small" items={items} />;
}
