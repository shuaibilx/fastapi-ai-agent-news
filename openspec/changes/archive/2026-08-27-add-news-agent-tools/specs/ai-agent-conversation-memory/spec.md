## Purpose

为新闻 Agent 提供基于 Redis 的有界短期会话记忆，使同一认证用户能够在连续请求中引用最近对话，同时通过轮次、Token、过期时间和用户隔离避免上下文无限增长或数据泄露。

## ADDED Requirements

### Requirement: 用户与会话隔离的短期记忆

系统 SHALL 以认证用户和 `conversationId` 的组合隔离 Agent 对话记忆。客户端 MAY 在后续请求中重用服务端返回的 `conversationId`，但 MUST NOT 能仅凭该标识读取其他用户的记忆。

#### Scenario: 创建新会话

- **WHEN** 已认证用户发送 Agent 请求但未提供 `conversationId`
- **THEN** 系统创建不可预测的会话标识并在响应中返回

#### Scenario: 继续已有会话

- **WHEN** 同一认证用户提交此前返回的 `conversationId`
- **THEN** 系统将该用户对应会话的有效短期记忆加入本次 Agent 上下文

#### Scenario: 不同用户使用相同会话标识

- **WHEN** 另一认证用户提交与其他用户相同的 `conversationId`
- **THEN** 系统不得加载或暴露其他用户的任何历史消息

### Requirement: 最多保留五个完整问答轮次

系统 SHALL 为每个用户会话最多保存五个成功完成的问答轮次，每个轮次由一条用户消息和一条最终助手回答组成。系统 MUST NOT 将历史原始工具输出或中间推理过程作为持久会话轮次保存。

#### Scenario: 会话不超过五轮

- **WHEN** 会话中成功完成的问答不超过五轮
- **THEN** 系统按时间顺序保留所有完整问答轮次

#### Scenario: 写入第六轮

- **WHEN** 会话成功完成第六个问答轮次
- **THEN** 系统删除最旧完整轮次并保留最近五个完整轮次

#### Scenario: Agent 请求执行失败

- **WHEN** Agent 请求未产生成功的最终回答
- **THEN** 系统不得把该失败请求写成已完成的会话轮次

### Requirement: 受 Token 预算限制的上下文装载

系统 SHALL 在每次模型调用前对历史消息实施可配置的 Token 预算。系统 SHALL 始终优先保留当前用户消息，并从最新到最旧加入不超过五轮的完整历史问答对；系统 MUST NOT 为满足预算而留下孤立的半个问答轮次。

#### Scenario: 五轮历史处于 Token 预算内

- **WHEN** 最近五轮历史的估算 Token 数未超过配置上限
- **THEN** 系统将五轮完整历史加入 Agent 上下文

#### Scenario: 五轮历史超过 Token 预算

- **WHEN** 最近五轮历史的估算 Token 数超过配置上限
- **THEN** 系统从最旧轮次开始移除完整问答对，直到满足预算

#### Scenario: 当前消息较长

- **WHEN** 当前用户消息与必要系统上下文接近总输入预算
- **THEN** 系统优先移除历史消息，并对仍然超限的请求返回明确校验错误而不是静默截断用户意图

### Requirement: Redis 过期与不可用降级

会话记忆 SHALL 使用可配置的滑动 TTL。Redis 读取或写入不可用时，系统 SHALL 继续执行无记忆 Agent 请求，并在响应中报告记忆不可用；Redis 故障 MUST NOT 导致已有对话内容由客户端回传并被服务端盲目信任。

#### Scenario: 活跃会话刷新过期时间

- **WHEN** 系统成功读取或写入一个会话的记忆
- **THEN** 系统刷新该会话的滑动 TTL

#### Scenario: 会话已经过期

- **WHEN** 用户提交已没有 Redis 记录的 `conversationId`
- **THEN** 系统把它作为无历史的会话继续处理，且不返回其他会话内容

#### Scenario: Redis 不可用

- **WHEN** 读取或保存 Agent 记忆时 Redis 连接失败
- **THEN** Agent 以无记忆模式完成本次请求，并在响应中将记忆状态标记为不可用
