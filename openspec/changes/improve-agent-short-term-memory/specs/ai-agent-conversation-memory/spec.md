## MODIFIED Requirements

### Requirement: 用户与会话隔离的短期记忆

系统 SHALL 以认证用户和 `conversationId` 的组合隔离 Agent 对话记忆。客户端 MAY 在后续请求中重用服务端返回的 `conversationId`，但 MUST NOT 能仅凭该标识读取其他用户的记忆。系统 MUST 从认证用户身份与 `conversationId` 在服务端派生持久化线程标识，且不得把客户端提供的标识直接作为跨用户共享的持久化键。

#### Scenario: 创建新会话

- **WHEN** 已认证用户发送 Agent 请求但未提供 `conversationId`
- **THEN** 系统创建不可预测的会话标识并在响应中返回

#### Scenario: 继续已有会话

- **WHEN** 同一认证用户提交此前返回的 `conversationId`
- **THEN** 系统将该用户对应会话的有效短期记忆加入本次 Agent 上下文

#### Scenario: 不同用户使用相同会话标识

- **WHEN** 另一认证用户提交与其他用户相同的 `conversationId`
- **THEN** 系统不得加载或暴露其他用户的任何历史消息

#### Scenario: 服务端隔离持久化线程

- **WHEN** 系统为 Agent 请求加载或保存短期记忆
- **THEN** 系统仅使用由当前认证用户和 `conversationId` 派生的服务端线程标识访问持久化状态

### Requirement: 受 Token 预算限制的上下文装载

系统 SHALL 在每次模型调用前对 Agent 上下文实施可配置的总输入预算。会话消息在未达到可配置的 Token 触发阈值时 SHALL 保持原始内容；达到阈值时，系统 SHALL 将较旧会话消息压缩为持久摘要，并保留最近的可配置消息窗口。系统 SHALL 始终优先保留当前用户消息，并保持工具调用与其结果的会话结构完整。

#### Scenario: 五轮历史处于 Token 预算内

- **WHEN** 当前会话状态的消息 Token 数低于摘要触发阈值
- **THEN** 系统在本次 Agent 上下文中保留已有会话消息原文且不生成历史摘要

#### Scenario: 五轮历史超过 Token 预算

- **WHEN** 当前会话状态的消息 Token 数达到或超过摘要触发阈值
- **THEN** 系统将较旧消息压缩为摘要、保留最近消息窗口，并将压缩后的状态用于后续同一会话请求

#### Scenario: 摘要后继续会话

- **WHEN** 用户在已压缩历史的同一会话中继续提问
- **THEN** 系统向 Agent 提供持久摘要、保留的最近消息和当前用户消息

#### Scenario: 当前消息较长

- **WHEN** 当前用户消息与必要系统上下文接近总输入预算
- **THEN** 系统优先压缩或移除可压缩历史，并对仍然超限的请求返回明确校验错误而不是静默截断用户意图

#### Scenario: 摘要服务不可用

- **WHEN** 需要压缩历史但摘要模型无法生成可用摘要
- **THEN** 系统返回明确的服务不可用错误，且不得用不完整摘要覆盖已有会话状态

### Requirement: Redis 过期与不可用降级

短期会话状态 SHALL 使用可配置的保留或失活清理策略。Redis 读取、写入或状态初始化不可用时，系统 SHALL 继续执行无记忆 Agent 请求，并在响应中报告记忆不可用；Redis 故障 MUST NOT 导致已有对话内容由客户端回传并被服务端盲目信任。

#### Scenario: 活跃会话刷新过期时间

- **WHEN** 系统成功加载或保存一个会话的短期状态
- **THEN** 系统按照配置的会话保留策略维持该会话的可恢复状态

#### Scenario: 会话已经过期

- **WHEN** 用户提交已被保留策略清理的 `conversationId`
- **THEN** 系统把它作为无历史的会话继续处理，且不返回其他会话内容

#### Scenario: Redis 不可用

- **WHEN** 读取、保存或初始化 Agent 短期状态时 Redis 连接失败
- **THEN** Agent 以无记忆模式完成本次请求，并在响应中将记忆状态标记为不可用

## ADDED Requirements

### Requirement: 持久化前的敏感信息保护

系统 MUST 在会话消息或摘要进入短期持久化状态前处理敏感信息。可识别个人信息 SHALL 按服务端策略脱敏；凭据型敏感信息 SHALL 被阻断，且不得发送给模型或写入短期记忆。系统 MUST NOT 依赖客户端对历史消息的过滤结果。

#### Scenario: 会话消息包含个人信息

- **WHEN** 用户消息包含被配置为脱敏的个人信息
- **THEN** 写入会话状态和发送给模型的对应内容使用脱敏后的值

#### Scenario: 会话消息包含凭据

- **WHEN** 用户消息包含被配置为阻断的 API Key、访问令牌或私钥等凭据型敏感信息
- **THEN** 系统拒绝该次 Agent 请求，且不向模型或短期持久化状态写入该消息

#### Scenario: 已有历史包含可检测敏感信息

- **WHEN** 系统加载的会话状态中包含可被当前策略检测的敏感信息
- **THEN** 系统在将其再次用于 Agent 上下文前按当前策略处理，且不得把原始敏感内容提供给模型

## REMOVED Requirements

### Requirement: 最多保留五个完整问答轮次

**Reason**: 固定问答轮次数量不能根据实际 Token 占用稳定控制上下文，也会在未超过模型预算时过早丢失有效会话信息。

**Migration**: 停止写入和读取旧的固定轮次 Redis List；使用同一 `conversationId` 的持久化线程状态和 Token 阈值摘要策略继续会话，旧 List 键按其原有保留策略自然清理。
