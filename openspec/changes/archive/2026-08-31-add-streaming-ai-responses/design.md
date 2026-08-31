## Context

现有 `POST /api/ai/qa` 与 `POST /api/ai/agent` 都返回一次性 JSON。QA 通过 `LangChainQaGateway.answer()` 调用模型；Agent 通过 `LangChainNewsAgentRunner.ainvoke()` 运行已命名的 `news_agent`，并在结束后从完整消息收集引用、工具摘要和记忆状态。当前 Vue `AIChat` 使用 Axios 等待 Agent 的完整结果。有关用户价值和范围见 [proposal.md](proposal.md)。

项目已使用 LangChain 1.3 和 LangGraph 1.2，适合在 Agent 边界使用事件流，并在服务层将其规范化为本项目的 SSE 事件。现有敏感信息中间件、只读工具和会话 checkpoint 必须继续有效。

## Goals / Non-Goals

**Goals:**

- 为 QA 和 Agent 提供相同的、经过 Bearer Token 认证的 POST SSE 传输模型。
- 只将用户可见的最终回答 token、可信新闻引用和安全的 Agent 工具状态转成 SSE 事件。
- 让现有 Agent 页面逐字显示、展示工具状态并支持主动停止；保持非流式 API 与既有前端调用兼容。
- 在断连、取消和流开始后的失败场景下提供不伪造完成状态的确定性行为。

**Non-Goals:**

- 不创建独立 QA 页面、不修改收藏/历史/新闻的业务语义，也不增加新的 Agent 工具。
- 不暴露思维链、推理 token、工具参数或原始工具输出，不实现自动重连、事件 ID、断点续传或历史回放。
- 不改变 Redis、MySQL、向量索引和 Agent 记忆数据模型；取消请求不承诺回滚已由底层 checkpointer 正常持久化的状态。

## Decisions

### 使用独立的 POST SSE 端点并保留 JSON 端点

新增 `/api/ai/qa/stream` 和 `/api/ai/agent/stream`，请求模型与既有 `QaRequest`、`AgentRequest` 相同。浏览器使用 `fetch` 提交带 Authorization 头的 POST 并读取 `ReadableStream`；原生 `EventSource` 不能可靠附带现有 Bearer Token，因此不采用。既有 JSON 端点继续调用一次性服务路径，以避免破坏其他客户端和现有测试。

备选方案是以 `Accept` 协商让同一路径在 JSON/SSE 间切换。未采用，因为同一 POST 路径的两种终端响应会增加客户端、异常处理和 OpenAPI 的歧义。

### 以领域事件封装底层 LangChain 流

新增流式适配层，将 QA 模型的异步 token 流和 Agent 的 LangGraph 事件流转换为固定 SSE 名称与 JSON 数据。公共事件为 `meta`、`delta`、`citation`、`done`、`error`、`ping`；Agent 额外使用 `tool`。流式事件仅表达客户端所需的领域状态，不直接透传 LangChain 原始事件结构。

Agent 使用已命名 `news_agent` 的事件流区分最终模型文本和工具生命周期；只有最终用户可见的文本作为 `delta`。工具事件仅从受控的工具元数据生成安全摘要。QA 在检索完成后固定引用集，再流式生成回答；无检索结果时直接产生拒答事件而不调用模型。

备选方案是将 LangChain `stream` 或 `astream_events` 原样输出给浏览器。未采用，因为版本、模型与内部节点结构会成为公共 API，并可能泄露推理或工具细节。

### 用单个异步 SSE 生成器管理保活、错误与取消

路由使用 FastAPI `StreamingResponse` 返回通用异步事件生成器。生成器在等待下一业务事件时设置保活超时；超时即发送 `ping`，而业务事件到达后继续发送。生成前的认证、Pydantic 校验和敏感信息拦截保持常规 HTTP 错误；响应开始后捕获受控服务错误并发送 `error`。

每次迭代检查 `Request.is_disconnected()`，并在浏览器 Abort 或任务取消时关闭下层异步迭代器。取消不发送 `done`，不自动重试，也不冒充成功；服务端保留已有的日志与 checkpoint 自身一致性边界。

### 前端使用渐进式 SSE 解析与 AbortController

`Front-end/src/api/ai.js` 新增 fetch 流读取帮助函数：检查 HTTP 错误、使用 `TextDecoder` 缓存不完整分块、按 SSE 空行边界解析 `event`/`data`，再将已解析事件回调给页面。`AIChat.vue` 创建 AI 占位消息，收到 `delta` 立即追加文本，收到 `tool` 更新状态，收到 `citation`/`done` 更新引用与最终元数据；发送按钮在生成中替换为停止按钮。

备选方案是继续使用 Axios。未采用，因为现有 Axios 请求封装适合完整响应，无法作为该页面流式事件的可靠、可取消读取边界。

## Risks / Trade-offs

- [上游模型或 LangGraph 事件结构与预期不同] → 在独立 Runner/Gateway 适配器中归一化，并用假流与真实服务边界测试事件过滤。
- [代理缓冲或空闲连接关闭] → 设置 SSE 响应头并定期发送 `ping`；开发文档记录反向代理需要关闭缓冲。
- [断连时下游任务继续消耗资源] → 通过 `is_disconnected()`、取消传播和异步迭代器关闭尽早停止；不承诺撤销已完成的只读查询或已保存 checkpoint。
- [流式事件泄露内部数据] → 白名单事件字段，重用既有脱敏策略，并测试拒绝推理、工具输入和原始结果。
- [前端网络分块不完整或事件顺序错误] → 编写纯解析器测试并只在 `done` 时标记请求成功。

## Migration Plan

1. 增加后端流式领域事件、QA/Agent 流式适配器和 SSE 路由，保留 JSON 路由。
2. 为流协议、安全过滤、取消和错误行为建立单元与 API 测试，再接入 Agent 页面。
3. 在本地配置实际模型服务时手动验证 token、工具状态、停止生成、认证失败和供应商中断。
4. 回滚时停止使用两个 `/stream` 端点并让前端恢复既有 JSON 调用；不需迁移或清理数据。
