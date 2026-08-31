## ADDED Requirements

### Requirement: 已认证的流式新闻 Agent

系统 SHALL 向已认证用户提供 `POST /api/ai/agent/stream`，接受与现有 Agent 相同的非空消息和可选 `conversationId`，并以 SSE 返回最终回答。该接口 MUST 继承现有 Agent 的敏感信息策略、只读工具边界、认证用户上下文隔离、执行限制和会话记忆策略；现有 `POST /api/ai/agent` JSON 接口 SHALL 保持可用且契约不变。

#### Scenario: 流式 Agent 最终回答

- **WHEN** 已认证用户以有效消息调用 `POST /api/ai/agent/stream`
- **THEN** 系统发送可见的最终回答文本增量，并在完成事件中返回可信引用、去重后的安全工具摘要、`conversationId` 和记忆状态

#### Scenario: 发送安全工具状态

- **WHEN** Agent 在流式请求中执行新闻、收藏或浏览历史只读工具
- **THEN** 系统可发送工具名称、受限状态和安全摘要，但不得发送工具参数、原始结果、其他用户数据或被策略阻断的敏感信息

#### Scenario: 流式 Agent 请求被取消

- **WHEN** 客户端在 Agent 流式请求完成前主动停止生成或连接断开
- **THEN** 系统停止本次 Agent 执行并且不发送成功完成事件，后续请求仍按现有会话与用户隔离策略处理

#### Scenario: 流式 Agent 预检失败

- **WHEN** 请求未认证、消息为空或消息包含被阻断的凭据型敏感信息
- **THEN** 系统在启动 SSE 前按现有稳定错误语义拒绝请求，且不会执行 Agent、工具或会话持久化
