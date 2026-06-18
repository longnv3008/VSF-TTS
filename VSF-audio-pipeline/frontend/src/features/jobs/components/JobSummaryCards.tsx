import { Card, Col, Row, Statistic } from "antd";
import type { Job } from "../../../entities/job/model";

type JobSummaryCardsProps = {
  jobs: Job[];
};

export default function JobSummaryCards({ jobs }: JobSummaryCardsProps) {
  return (
    <Row gutter={[16, 16]}>
      <Col xs={24} md={8}>
        <Card>
          <Statistic title="Tong jobs" value={jobs.length} />
        </Card>
      </Col>
      <Col xs={24} md={8}>
        <Card>
          <Statistic title="Dang chay" value={jobs.filter((job) => job.status === "running").length} />
        </Card>
      </Col>
      <Col xs={24} md={8}>
        <Card>
          <Statistic title="Hoan thanh" value={jobs.filter((job) => job.status === "completed").length} />
        </Card>
      </Col>
    </Row>
  );
}
