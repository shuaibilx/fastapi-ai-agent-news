## 1. Redis checkpointer 运行时基础

- [x] 1.1 在 `pyproject.toml` 中添加受支持的 `langgraph-checkpoint-redis` 依赖并更新锁文件，使用隔离 Redis 运行 `AsyncRedisSaver` 的连接、`asetup`、读写和关闭集成检查
- [x] 1.2 为 checkpointer 编写失败测试，覆盖服务端派生的线程标识、相同 `conversationId` 的跨用户隔离、线程恢复和初始化失败；实现不向浏览器或模型暴露 `thread_id` 的线程标识工厂
- [x] 1.3 在应用生命周期中实现 checkpointer 的幂等初始化、关闭和健康状态管理，并通过集成测试验证当前 Redis 部署不支持初始化时应用进入明确的无记忆降级或就绪失败路径
- [x] 1.4 实现可配置的会话保留与失活清理机制，使用 checkpointer 的公开 API 或受控索引而非内部键名扫描，并通过集成测试验证过期线程不再恢复且不会影响其他线程

## 2. Token 摘要与服务端配置

- [x] 2.1 先为摘要 trigger、保留窗口、总输入安全余量、摘要模型回退和会话保留配置编写失败测试，覆盖不等式校验、默认值、环境变量加载和移除固定轮次运行时依赖
- [x] 2.2 在 `app/core/config.py`、`.env.example` 与配置测试中实现摘要与保留配置，确保 `keep < trigger < 可用总输入预算` 且摘要模型未配置时安全复用主模型
- [x] 2.3 先为 `SummarizationMiddleware` 编写失败测试，覆盖阈值内不摘要、达到阈值后压缩旧消息、保留最近窗口、后续请求复用摘要以及摘要失败不覆盖原状态
- [x] 2.4 在 Agent 工厂中接入 `SummarizationMiddleware`，协调其 Token 计数、`ContextEditingMiddleware` 和 `ModelCallLimitMiddleware`，运行 2.3 测试验证注册顺序和总输入边界

## 3. 敏感信息防护

- [x] 3.1 先为服务端敏感信息策略编写失败测试，覆盖邮箱、银行卡、IP、手机号和身份证号脱敏，以及 API Key、JWT、Bearer Token、私钥阻断；断言原始敏感值不进入模型消息或持久化状态
- [x] 3.2 实现可复用的服务端 sanitizer、受控自定义检测器和 `PIIMiddleware` 组合，覆盖 Agent 输入、模型输出与工具结果，并运行 3.1 测试确认策略不能由客户端关闭或替换
- [x] 3.3 为工具 artifact 到应用响应的路径编写失败测试，覆盖最终回答、新闻引用和工具摘要中的个人信息脱敏及凭据型信息安全失败摘要
- [x] 3.4 在 `collect_tool_metadata` 与 API 响应映射前接入同一 sanitizer，运行 3.3 测试确认 artifact 不会绕过 LangChain 消息中间件

## 4. Agent 会话迁移与故障降级

- [x] 4.1 先为 Agent service/runner 编写失败测试，覆盖每次仅提交当前消息、checkpointer 恢复同一会话、`loaded`/`empty`/`unavailable` 状态、Redis 故障时无记忆执行和不重试已执行的工具调用
- [x] 4.2 实现 stateful/stateless Agent runner 与会话状态门面，将派生线程标识和 checkpointer 配置传给 LangGraph，并运行 4.1 测试确认认证隔离和 Redis 降级保持有效
- [x] 4.3 删除旧 `ConversationMemoryStore`、`ConversationTurn`、固定五轮 List 裁剪和手工历史拼接的运行时路径，保留旧 `ai:agent:memory:v1:*` 键自然过期，并通过回归测试确认没有新读写旧键
- [x] 4.4 为摘要后的多工具会话编写集成测试，验证工具调用及结果成对、工具上下文仍受上限控制、敏感信息先于摘要处理且后续追问可使用摘要中的关键上下文

## 5. API、前端与回归验证

- [x] 5.1 扩展 `POST /api/ai/agent` API 测试，覆盖凭据型输入的安全校验错误、个人信息脱敏、既有请求/成功响应契约、跨用户会话隔离和 Redis 无记忆降级
- [x] 5.2 更新前端 API/组件测试与必要提示文案，验证 `conversationId` 续用和“新对话”行为不变，并在服务端返回安全错误或记忆不可用时展示安全反馈；运行前端测试和生产构建
- [x] 5.3 运行完整后端测试套件、隔离 Redis 集成测试、前端生产构建与 `openspec validate improve-agent-short-term-memory --strict`，确认没有引入长期记忆、向量检索、写入工具或 SSE
