## Context

参见 `proposal.md` 的动机。当前后端已经有受认证的 `POST /api/ai/qa`、关键词 `NewsRetrievalService`、服务端 LLM 配置、异步 SQLAlchemy 服务和通用 Redis 客户端；前端 `AIChat.vue` 目前只发送当前问题。`app/ai/agent` 仍为空占位目录，项目安装了模型供应商适配器但尚未声明顶层 `langchain` Agent 运行时依赖。

本 Change 横跨 Agent 编排、业务服务适配、认证边界、Redis 会话状态、API 契约和前端，因此需要在实现前固定工具职责、上下文预算和故障降级方式。行为契约见 `specs/ai-news-agent/spec.md` 与 `specs/ai-agent-conversation-memory/spec.md`。

## Goals / Non-Goals

**Goals:**

- 建立一个可替换模型供应商的单 Agent 编排层，并把所有业务访问限制在显式注册的只读工具中。
- 让直接 QA 与 Agent 共享同一个新闻检索抽象，后续语义检索只替换该抽象的实现。
- 将认证身份、数据库会话和服务端限制作为可信运行时上下文注入工具，而不是模型可构造的参数。
- 用现有 Redis 保存五个完整问答轮次，并在 Agent 的每次模型调用前同时执行轮数和 Token 预算约束。
- 从工具执行结果中确定性收集引用和安全工具摘要，不依赖模型生成结构化来源。
- 通过依赖注入和假模型/假工具实现确定性的单元与 API 测试。

**Non-Goals:**

- 不把 Agent 替代为唯一问答入口，`POST /api/ai/qa` 继续服务固定新闻问答场景。
- 不提供添加收藏、删除历史或其他写入型工具，也不引入人工审批流程。
- 不保存模型中间推理、完整历史工具结果、长期用户画像或跨会话记忆。
- 不引入 Redis Vector、Redis Stack 检查点、Embedding、向量数据库、多 Agent 或 SSE。
- 不在本阶段优化关键词召回质量；Phase 4 将替换检索实现。

## Decisions

### 1. 使用单个 LangChain `create_agent` 作为编排核心

在 `app/ai/agent` 下建立 Agent 工厂、工具适配器、会话记忆和应用服务。Agent 工厂使用现有 OpenAI-compatible 模型配置，注册固定工具集合并设置系统提示词、最大执行轮次和上下文中间件；路由只负责认证、依赖装配和响应映射。

选择单 Agent 是因为四个工具都属于同一新闻业务域，当前不需要任务委派或多角色协作。备选方案是手写意图分类和 `if/elif` 路由，但它不能体现 Agent 自主选择与多工具组合能力；多 Agent 则会增加状态与调试复杂度，超出本阶段需要。

### 2. 工具只包装应用读取能力，不直接承载路由或 ORM 对象

注册以下工具：

- `search_news_knowledge(query, limit)`：调用 `NewsRetrievalService.search`，返回压缩后的新闻片段；
- `get_news_detail(news_id)`：调用新闻详情服务并映射为可序列化的只读 DTO；
- `list_my_favorites(page, page_size)`：使用认证用户 ID 查询收藏并限制分页大小；
- `list_my_history(page, page_size)`：使用认证用户 ID 查询浏览历史并限制分页大小。

工具参数只包含模型可以合理选择的业务参数。`user_id`、请求级 `AsyncSession` 和上限配置通过类型化运行时上下文提供，且不进入模型看到的工具 schema。工具结果先映射成小型 DTO，避免把 SQLAlchemy 状态、整篇无界正文或内部字段交给模型。

备选方案是让工具直接调用 API 路由，或者直接返回 ORM 对象。前者重复认证和 HTTP 序列化，后者容易泄露内部字段且不能稳定控制上下文，因此都不采用。

### 3. Agent 复用检索层，而不嵌套完整 `QaService`

`search_news_knowledge` 直接复用 `NewsRetrievalService`。它把适合模型阅读的有限文本放入工具消息内容，并把新闻 ID、标题和摘录作为应用侧元数据随工具结果保留；Agent 最终回答由当前 Agent 模型生成。Agent 服务在执行结束后从工具消息元数据收集并去重引用。

直接 QA 仍按 `QaService -> NewsRetrievalService -> QaGateway` 运行。这形成两个上层消费者共享一个检索端口的结构，Phase 4 只需替换检索实现。

备选方案是把完整 `QaService.ask()` 暴露为工具。那会形成“Agent 模型 → QA 模型 → Agent 模型”的嵌套生成，增加成本、延迟和重复回答，因此不采用。

### 4. Agent API 使用稳定的应用响应契约

新增 `POST /api/ai/agent`：

- 请求包含 `message` 和可选 UUID 格式 `conversationId`；
- 未提供会话标识时由服务端生成并返回；
- 成功数据包含 `answer`、`conversationId`、`citations`、`toolCalls` 和 `memoryStatus`；
- `toolCalls` 只返回工具名称、成功或失败状态以及面向用户的简短说明，不返回数据库连接、供应商参数或隐藏上下文；
- `memoryStatus` 使用 `loaded`、`empty`、`unavailable`，分别表示加载到历史、没有有效历史、Redis 读写发生故障；
- 使用既有 `success_response` 包装，并把供应商不可用和执行上限映射为稳定的 HTTP/应用错误。

保留 `/api/ai/qa` 可让明确的新闻问答继续走更短、更可预测的固定链路。前端 AI 对话页切换到 Agent 接口，并仅保存本会话返回的 `conversationId`；“新对话”通过丢弃该标识并发起新会话实现，无需新增删除记忆接口。

### 5. 使用 Redis List 保存五轮最终对话，而不是完整图检查点

为每个会话使用键：

```text
ai:agent:memory:v1:{user_id}:{conversation_id}
```

每个 List 元素是一轮 JSON，仅包含用户消息、最终助手回答和完成时间。成功回答后使用 Redis transaction pipeline 执行 `RPUSH`、`LTRIM -5 -1` 和 `EXPIRE`，从存储层保证最多五轮并刷新滑动 TTL。加载时使用 `LRANGE`，不信任客户端回传的历史消息。

该方案直接满足“五轮最终问答”的需求，并兼容当前普通 Redis 部署。完整 LangGraph Checkpointer 会持久化更多图状态和工具消息，适合中断恢复或人工审批，但会放大存储和裁剪复杂度；当前只读、单请求完成的 Agent 不需要它。

默认配置建议为：

```text
AI_AGENT_HISTORY_MAX_ROUNDS=5
AI_AGENT_HISTORY_MAX_TOKENS=3000
AI_AGENT_TOOL_RESULT_MAX_TOKENS=4000
AI_AGENT_INPUT_MAX_TOKENS=10000
AI_AGENT_MEMORY_TTL_SECONDS=86400
AI_AGENT_MAX_ITERATIONS=6
```

这些限制必须由服务端配置控制。历史轮数固定默认五轮但保留配置校验，方便在不同模型上下文窗口下调整。

### 6. 轮数限制、Token 预算和工具结果上限分层执行

上下文构建顺序为：系统提示与工具 schema、最近历史、当前用户消息、当前轮工具消息。加载历史时从最新到最旧选择完整问答对，达到 `AI_AGENT_HISTORY_MAX_ROUNDS` 或 `AI_AGENT_HISTORY_MAX_TOKENS` 即停止；当前消息始终优先保留。

Token 计数通过独立 `TokenBudgetPolicy` 完成：优先使用模型适配器提供的计数能力，不可用时使用保守的近似计数器。Agent 的模型前中间件在每次循环调用模型前再次检查总输入预算，并保持 AI tool call 与对应 tool result 成对。每个工具还在产生结果时执行自己的条数、字符数或 Token 上限，因此不会依赖最后一步粗暴截断。

如果移除全部历史后，当前消息与必要系统上下文仍超过总输入预算，接口返回明确校验错误，不静默改变用户当前问题。

### 7. Redis 故障只关闭记忆，不关闭 Agent 核心能力

Agent 专用 `ConversationMemoryStore` 明确区分“键不存在”和“Redis 操作失败”。键不存在对应 `empty`；读取或写入异常对应 `unavailable`，记录结构化日志后继续执行。读取失败时以空历史运行；写入失败时仍返回已经生成的回答，但响应标记记忆不可用。

备选方案是让 Redis 故障导致整个 Agent 返回 503。记忆并非生成当前答案的必要依赖，这会不必要地降低可用性，因此不采用。模型供应商或无法完成的核心工具故障仍按 Agent 服务错误处理。

### 8. 测试按纯策略、工具、Agent 服务和 API 四层隔离

- 纯策略测试验证五轮裁剪、Token 预算、完整问答对和引用去重；
- 工具测试使用假服务/测试数据库验证参数上限、DTO 映射和 `user_id` 隔离；
- Agent 服务测试使用可预测的假聊天模型或注入式 Agent runner 验证工具轨迹、引用和故障映射；
- API 测试覆盖认证、空消息、会话 ID、Redis 降级和统一响应结构；
- 前端构建与组件/API 测试验证 `conversationId` 延续、新对话、引用及工具摘要显示。

测试不得调用真实模型供应商，也不得依赖外部 Redis；Redis 行为通过 fake 或隔离测试实例验证。

## Risks / Trade-offs

- [模型可能选择错误工具或重复调用] → 使用清晰工具描述、互斥场景示例、最大执行轮次和工具轨迹测试约束行为。
- [关键词检索限制 Agent 回答质量] → 保持共享检索端口，Phase 4 替换为语义检索而不修改 Agent/QA 契约。
- [近似 Token 计数与供应商真实 tokenizer 存在偏差] → 使用保守安全余量、工具侧结果上限和总输入硬限制，并允许后续接入精确 tokenizer。
- [Redis 中五轮对话仍可能包含敏感用户输入] → 用户与会话组合键隔离、短 TTL、服务端生成不可预测标识，日志不记录完整消息正文。
- [同一会话并发请求可能按完成顺序写入] → Redis pipeline 保证单次追加和裁剪原子执行，前端在请求期间禁用重复发送；多端严格排序留待确有需求时引入会话锁或序列号。
- [工具执行成功但模型最终失败] → 不保存失败轮次；记录工具级诊断信息但不向客户端暴露内部异常。
- [Redis 写入失败导致本次回答不能在下一轮延续] → 当前回答仍返回且 `memoryStatus=unavailable`，客户端可提示记忆暂不可用。

## Migration Plan

1. 添加并锁定顶层 LangChain Agent 依赖，确认与现有 `langchain-openai`、`langchain-deepseek` 和 Python 版本兼容。
2. 在 `app/core/config.py` 与 `.env.example` 增加 Agent 执行、历史、Token 和 TTL 配置，保持供应商凭据仅在服务端。
3. 实现会话 DTO、`TokenBudgetPolicy` 和 Redis `ConversationMemoryStore`，先完成纯策略与故障降级测试。
4. 实现四个只读工具适配器、类型化运行时上下文、引用元数据收集和用户隔离测试。
5. 实现 Agent 工厂与服务，接入现有检索层并完成假模型编排测试。
6. 增加 API schema、依赖装配和 `POST /api/ai/agent`，保留 `/api/ai/qa` 回归测试。
7. 更新前端 API 和 `AIChat.vue`，支持会话延续、新对话、引用与工具摘要。
8. 运行后端测试、OpenSpec 严格校验和前端构建后部署；无需数据库迁移，Redis 键按 TTL 自动清理。

回滚时移除 Agent 路由注册和前端入口切换即可，现有 `/api/ai/qa` 不受影响；遗留 `ai:agent:memory:v1:*` 键可等待 TTL 自动过期，无需执行破坏性删除。
