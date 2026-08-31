## Why

当前新闻 QA 与 Agent 必须等待模型和工具调用全部完成后才返回结果，用户无法看到生成进度，也无法主动停止耗时请求。语义检索与受控 Agent 已完成，现阶段可以在不改变既有 JSON 契约的前提下提供安全、可取消的 SSE 流式交互。

## What Changes

- 新增经认证的 `POST /api/ai/qa/stream` 和 `POST /api/ai/agent/stream` SSE 接口，保留现有 `/qa`、`/agent` JSON 接口不变。
- 为两条流式接口定义一致的结构化事件协议：元数据、最终回答文本增量、新闻引用、完成与安全错误；Agent 额外发送安全的工具执行状态。
- 让 QA 与 Agent 的最终用户可见回答按增量输出，但不向客户端暴露模型思维链、工具参数、工具原始结果、供应商凭据或其他敏感信息。
- 将现有 Agent 聊天页面改为使用 `fetch` 读取 SSE，实时渲染文本和工具状态，并通过 `AbortController` 提供停止生成能力。
- 处理客户端断连、模型/工具故障和长时间无输出的连接保活；流式失败通过稳定、已脱敏的 SSE 错误事件报告。

## Capabilities

### New Capabilities

- `ai-streaming-responses`: 定义 AI 响应的通用 SSE 事件、连接保活、取消与错误语义，并约束可向浏览器发送的安全数据范围。

### Modified Capabilities

- `ai-news-qa`: 为已认证新闻问答增加保持现有请求含义与引用约束的流式回答入口。
- `ai-news-agent`: 为已认证新闻 Agent 增加流式最终回答、受限工具状态、会话元数据与取消行为，同时保持只读和用户隔离要求。

## Impact

- 后端：`app/api/routers/ai.py`、`app/ai/rag/`、`app/ai/agent/`，以及新的 `app/ai/streaming/` 事件与 SSE 适配层。
- 前端：`Front-end/src/api/ai.js`、`Front-end/src/views/AIChat.vue`，从 Axios 单次响应切换为带 Bearer Token 的 `fetch` 流读取。
- 依赖与运行：复用 FastAPI、LangChain、LangGraph 的异步能力；不引入浏览器供应商凭据，不改变 Redis、MySQL 或向量索引的数据模型。
