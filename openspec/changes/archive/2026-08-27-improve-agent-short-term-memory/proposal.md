## Why

当前新闻 Agent 以 Redis List 固定保存五个完整问答轮次，再由应用层手动裁剪历史。这会在短对话中无谓丢失上下文，也会在长对话中只丢弃旧信息而无法保留其关键事实；同时，用户或工具结果中的敏感信息缺少覆盖模型、会话持久化和响应边界的一致防护。

现在应采用 LangChain/LangGraph 的持久化短期状态和预构建中间件，使会话仅在超过 Token 阈值时压缩旧内容，并让敏感信息在进入模型或 Redis 前受到确定性处理。

## What Changes

- 使用与 LangGraph 兼容的 Redis checkpointer 持久化 Agent 线程状态，替换当前 Redis List、固定轮次上限和手动历史拼接路径。
- 配置 `SummarizationMiddleware`：会话消息未达到可配置 Token 触发阈值时保留原文，超过阈值时将旧消息压缩为摘要并保留最近的可配置消息窗口。
- 保留总输入、工具结果和最大执行轮次等服务端边界，并协调摘要与工具上下文裁剪顺序，避免超过模型上下文窗口。
- 配置 `PIIMiddleware` 与受控的自定义检测器：对个人信息进行脱敏，对 API Key、JWT、Bearer Token、私钥等凭据型内容阻断；覆盖 Agent 输入、模型输出和工具结果。
- 在应用侧对引用和工具摘要执行同等敏感信息过滤，避免工具 artifact 绕过 LangChain 消息中间件。
- 保持 `POST /api/ai/agent` 的请求与成功响应结构、只读工具集合和认证用户边界兼容；Redis 状态不可用时继续允许无记忆单轮调用。
- 迁移后不读取旧的 `ai:agent:memory:v1:*` List 键；旧键仅按原 TTL 自然过期。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `ai-agent-conversation-memory`: 将短期会话记忆改为按 Token 阈值自动摘要的持久化线程状态，并增加敏感信息在持久化前的保护要求。
- `ai-news-agent`: 为 Agent 请求、工具结果和可追溯响应增加敏感信息阻断或脱敏行为，同时保持既有认证与只读工具契约。

## Impact

- 后端会调整 `app/ai/agent` 的 runner、factory、service、memory 相关模块及其依赖装配，移除不再适用的 Redis List 读写路径。
- `app/core/config.py`、`.env.example` 和配置测试将由轮数限制配置迁移到摘要 trigger、保留窗口、摘要模型和敏感信息策略配置。
- Python 依赖将增加 Redis checkpointer 集成；服务启动或部署需要执行其安全、幂等的初始化步骤。
- Redis 将使用 LangGraph checkpoint 数据结构保存按用户隔离的 Agent 线程；会话清理策略必须经过集成验证，不能假定旧 List 的 TTL 行为自动适用。
- API 外形和前端 `conversationId` 使用方式保持兼容，但前后端测试将覆盖敏感信息阻断/脱敏和记忆降级提示。
