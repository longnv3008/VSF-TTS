import { Layout, Typography } from "antd";
import type { ReactNode } from "react";

const { Header, Content } = Layout;
const { Title, Text } = Typography;

type AppShellProps = {
  children: ReactNode;
};

export default function AppShell({ children }: AppShellProps) {
  return (
    <Layout className="app-shell">
      <Header className="app-header">
        <div>
          <Title level={3} className="app-title">
            VinSmart Audio Pipeline
          </Title>
          <Text className="app-subtitle">
            Frontend, API, workflow, tracing, logging, storage
          </Text>
        </div>
      </Header>
      <Content className="app-content">{children}</Content>
    </Layout>
  );
}
