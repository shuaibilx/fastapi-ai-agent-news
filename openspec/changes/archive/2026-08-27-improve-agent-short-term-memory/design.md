## Context

参见 `proposal.md`。当前 Agent 在应用层从 Redis List 读取最多五个 `ConversationTurn`，用 `TokenBudgetPolicy` 选择若干完整问答对后再手工传入 `create_agent`。这不是 LangGraph 的线程状态，无法让 `SummarizationMiddleware` 将压缩后的历史持久用于下一次请求；同时当前中间件只清理过大的工具调用，未统一过滤输入、输出、会话持久化与工具 artifact。

项目已经使用异步 Redis、LangChain `create_agent` 和 `ChatDeepSeek`。已安装的 LangChain 版本提供 `SummarizationMiddleware` 与 `PIIMiddleware`；生产级跨请求短期记忆需要数据库型 checkpointer，而不是 `InMemorySaver`。

## Goals / Non-Goals

**Goals:**

- 让 `conversationId` 对应的 Agent 会话以持久化线程状态继续，未超过 Token 阈值时保留原文，超过阈值时稳定压缩旧历史。
- 在模型调用、工具消息、Redis 状态和应用响应四个边界执行一致的敏感信息策略。
- 保持现有 Agent API、只读工具、认证隔离、引用收集和 Redis 故障降级兼容。
- 以自动化测试验证 Redis checkpointer 部署前置条件、摘要触发、隔离、脱敏/阻断与降级行为。

**Non-Goals:**

- 不添加跨会话长期记忆、用户画像、向量记忆或语义检索。
- 不将客户端历史消息、敏感信息规则或 provider 凭据加入 API 契约。
- 不迁移旧 Redis List 中的原始文本，也不主动批量删除旧键。
- 不在本 Change 增加写入型 Agent 工具、人工审批或 SSE。

## Decisions

### 1. 使用 Redis-backed LangGraph checkpointer 作为唯一的短期会话存储

新增 `langgraph-checkpoint-redis`，在应用生命周期中创建并初始化 `AsyncRedisSaver`，将其传给 `create_agent`。每个请求只传当前 `HumanMessage`；同一线程的会话状态由 checkpointer 恢复和保存。现有 `ConversationMemoryStore`、`ConversationTurn`、固定五轮 List 裁剪及手工历史拼接路径将删除，不得让两种会话存储并行写入。

生产初始化必须作为启动或部署中的幂等步骤执行，并以一次真实 Redis 集成检查确认当前 Redis 部署满足该 checkpointer 的要求。若部署不支持所需数据结构或初始化失败，应用必须明确报告就绪失败或采用经过测试的无记忆降级路径，不能悄悄退回旧 List 实现。

选择该方案是因为 LangChain 将短期记忆定义为带 checkpointer 的线程状态，摘要中间件对该状态的更新才能跨请求持续生效。`InMemorySaver` 只适用于开发；继续手工保存摘要则会重复实现框架的状态语义。

### 2. 服务端派生线程标识，保留浏览器 `conversationId` 契约

浏览器继续接收并回传 UUID 格式的 `conversationId`。服务端构造不向客户端暴露的 `thread_id`，其命名空间包含固定 Agent 前缀、可信认证 `user_id` 和该 UUID；runner 仅把这个派生值交给 checkpointer 配置。

这避免两个用户提交相同 UUID 时命中同一持久线程。不会把 `user_id` 放进模型可见消息、工具 schema 或前端状态。

### 3. 用 Token 阈值摘要替代固定轮次数量

Agent 工厂注册 `SummarizationMiddleware`，使用服务端配置的摘要模型、`trigger=("tokens", trigger_tokens)` 和 `keep=("tokens", keep_tokens)`。低于 trigger 时不改变历史；达到 trigger 时，由摘要模型压缩较旧消息并保留最近窗口。摘要模型默认复用主模型配置，但可由仅服务端可见的可选模型名覆盖。

初始默认值以总输入预算为约束：摘要 trigger 为总输入预算的一部分，保留窗口小于 trigger，并为系统提示、工具 schema 与当前轮工具结果保留安全余量。配置模型需要交叉校验这些不等式，而不能让各阈值独立失控。

保留 `ContextEditingMiddleware` 处理瞬时工具结果膨胀，保留 `ModelCallLimitMiddleware` 约束成本和循环。中间件顺序固定为：敏感信息保护、摘要、工具上下文编辑、模型调用上限；测试必须确认该顺序使摘要和持久化状态只看到已过滤内容。

### 4. 采用分级、服务端控制的敏感信息策略

使用多个 `PIIMiddleware` 实例和受控自定义检测器：邮箱、银行卡、IP、手机号、身份证号等按 `redact` 处理；API Key、JWT、Bearer Token、私钥等凭据型内容按 `block` 处理。过滤同时应用到输入、模型输出和工具结果。

`PIIMiddleware` 覆盖 LangChain 消息，但引用和工具执行摘要从工具 artifact 收集，可能绕过消息链。因此在 `collect_tool_metadata` 后、API schema 映射前使用同一服务端 sanitizer 过滤最终回答、`citations` 与 `toolCalls`。敏感策略及自定义正则只位于服务端代码或环境配置，不向客户端暴露关闭开关。

选择“个人信息脱敏、凭据阻断”是为了继续支持含联系方式的新闻语境，同时避免令牌等高风险秘密进入模型或 Redis。仅靠提示词、只过滤输入或只依赖模型自我约束都不能保护工具结果与持久化状态。

### 5. 通过会话状态门面保留 Redis 故障降级和清理策略

在 runner 与 `AsyncRedisSaver` 之间建立小型会话状态门面：它在模型调用前检查 checkpointer 可用性，选择持久化 Agent 或无记忆 Agent，并将结果映射为已有的 `loaded`、`empty`、`unavailable` 状态。发生故障时不得把客户端提交的历史当作替代品；无记忆 Agent 只接收经敏感信息处理的当前消息。

checkpointer 的会话清理由专门的保留策略负责。实现前先验证所选 Redis saver 是否支持安全的线程级 TTL；若不支持，使用其公开的线程删除能力和受控的失活索引/后台清理，不得通过无界键扫描或直接猜测其内部 Redis 键名删除状态。旧 `ai:agent:memory:v1:*` 键不迁移，等待原 TTL 过期。

### 6. 先建立可重复的运行时与安全测试，再替换旧路径

测试使用假的 summary model、假的工具、可控 checkpointer 和隔离 Redis 集成环境。安全测试同时断言“模型收到的消息”“持久化状态”“API 响应”均没有原始敏感文本；不能只测试 HTTP 错误码。checkpointer 兼容性和初始化测试位于依赖安装后、代码迁移前，避免在不支持的 Redis 环境中完成大面积替换才暴露基础设施问题。

## Risks / Trade-offs

- [摘要增加额外模型调用、延迟与成本] → 只在 Token trigger 达到时调用，保留窗口避免频繁重复摘要，并记录摘要触发和失败的结构化指标。
- [摘要遗漏细节或改变措辞] → 用专门测试验证关键信息在后续追问中仍可用；不将摘要用于独立事实来源，新闻事实仍通过只读工具获取。
- [Redis checkpointer 与当前 Redis 部署不兼容] → 首先执行真实 `asetup` 集成检查；不通过时在替换实现前停止并升级 Redis 部署或选择受支持的持久化后端。
- [中间件顺序错误导致原始内容先被摘要或持久化] → 固定注册顺序，并用输入、工具结果、输出与 Redis 四类测试验证实际数据流。
- [PII 规则对新闻文本产生误报] → 个人信息优先使用可解释的 `redact`，仅对凭据型模式 `block`；规则通过服务端版本化配置与测试样例维护。
- [状态写入在模型生成后失败] → 状态门面不得重试整次 Agent 调用以避免重复工具调用；返回已生成的安全结果并标记 `memoryStatus=unavailable`，或在未产生可用结果时返回明确错误。

## Migration Plan

1. 增加 Redis checkpointer 依赖和开发环境集成测试，验证 `AsyncRedisSaver` 的连接、初始化、读写、线程隔离与安全清理能力。
2. 增加摘要、保留、总输入预算和敏感信息策略的服务端配置及交叉校验；更新 `.env.example`，移除轮数配置的运行时依赖。
3. 先实现敏感内容检测与应用侧 sanitizer，并为输入、输出、工具 artifact 和持久化状态建立失败测试。
4. 实现 stateful/stateless Agent runner、服务端线程标识和中间件组合；替换 Redis List 读写和手工历史选择逻辑。
5. 使用假模型和隔离 Redis 完成摘要触发、会话延续、跨用户隔离、Redis 降级、工具上下文上限与 API/前端回归测试。
6. 部署时执行一次 checkpointer 初始化；监控摘要触发率、摘要失败率、内存不可用率和安全阻断率。回滚时恢复上一版无 checkpointer 的 Agent runner，旧 List 键仍不读取且按 TTL 自然过期。
