import { Button, Card, Form, Input, Typography } from "antd";

const { Paragraph } = Typography;

export type CreateJobValues = {
  batch_name: string;
  urls: string;
};

type CreateJobFormProps = {
  loading: boolean;
  onSubmit: (values: CreateJobValues) => Promise<void>;
};

export default function CreateJobForm({ loading, onSubmit }: CreateJobFormProps) {
  const [form] = Form.useForm<CreateJobValues>();

  async function handleFinish(values: CreateJobValues) {
    await onSubmit(values);
    form.resetFields(["urls"]);
  }

  return (
    <Card title="Tao ingest job">
      <Paragraph>
        Nhap danh sach YouTube URL. Backend worker se crawl audio, normalize thanh WAV, trich xuat translate full video va tao metadata.
      </Paragraph>
      <Form<CreateJobValues>
        layout="vertical"
        form={form}
        initialValues={{ batch_name: "batch_001", urls: "" }}
        onFinish={handleFinish}
      >
        <Form.Item label="Batch name" name="batch_name" rules={[{ required: true }]}>
          <Input placeholder="batch_001" />
        </Form.Item>
        <Form.Item label="YouTube URLs" name="urls" rules={[{ required: true, message: "Nhap it nhat 1 URL" }]}>
          <Input.TextArea
            rows={8}
            placeholder={"https://www.youtube.com/watch?v=...\nhttps://www.youtube.com/playlist?list=..."}
          />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={loading}>
          Chay pipeline
        </Button>
      </Form>
    </Card>
  );
}
