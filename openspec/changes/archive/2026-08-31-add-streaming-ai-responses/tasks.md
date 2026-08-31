## 1. 通用 SSE 事件与测试基础

- [x] 1.1 先为 SSE 事件编码、JSON 负载白名单、终止事件顺序、保活和取消行为编写失败测试；验证测试能拒绝 `done` 后继续输出、内部字段泄露和取消后的成功完成。
- [x] 1.2 实现 `app/ai/streaming/` 的领域事件、SSE 序列化与异步流协调器；验证 1.1 测试通过且事件使用 `text/event-stream` 格式。

## 2. 流式新闻 QA

- [x] 2.1 先为 QA 流式 Gateway/Service 编写失败测试，覆盖检索后 token 增量、引用、无结果拒答不调用模型、流开始后的供应商错误和取消；验证测试在实现前失败。
- [x] 2.2 为 `QaGateway` 与 `QaService` 增加流式适配路径，并保持现有 `ask()` 与 JSON 契约不变；验证 2.1 测试和既有 QA 测试通过。
- [x] 2.3 新增 `POST /api/ai/qa/stream` 并编写 API 测试，覆盖认证/空问题的常规 HTTP 错误及成功/失败 SSE 事件；验证响应头、事件顺序和非流式 `/api/ai/qa` 回归通过。

## 3. 流式新闻 Agent

- [x] 3.1 先为 Agent Runner/Service 流式事件编写失败测试，覆盖仅发送最终可见文本、安全工具状态、引用与会话元数据、内部推理/参数过滤和取消；验证测试在实现前失败。
- [x] 3.2 实现 LangChain/LangGraph 事件到 Agent 领域事件的适配器，并让 Agent 服务在完成时复用既有安全清洗、引用收集和记忆状态逻辑；验证 3.1 测试及既有 Agent 服务测试通过。
- [x] 3.3 新增 `POST /api/ai/agent/stream` 并编写 API 测试，覆盖用户隔离、预检敏感信息、工具状态、流开始后错误和取消不发送 `done`；验证现有 `/api/ai/agent` JSON API 契约保持不变。

## 4. Agent 聊天页面流式交互

- [x] 4.1 在 `Front-end/src/api/ai.js` 实现带 Bearer Token 的 POST SSE `fetch` 消费器，正确处理被拆分的 UTF-8/事件分块、HTTP 错误、`error` 事件和 `AbortController`；验证对受控模拟流的解析结果与取消行为正确。
- [x] 4.2 将 `AIChat.vue` 改为逐步追加 `delta`、展示安全工具状态和引用/完成元数据，并将生成中的发送操作替换为停止生成；验证登录态下可开始、停止和开始新对话，且不会保留已取消请求为成功回答。
- [x] 4.3 更新 README 的流式接口、浏览器调用方式、SSE 事件表、反向代理缓冲与本地手动验证说明；验证新开发者可按说明调用两个接口并理解取消与回滚边界。

## 5. 端到端验证

- [x] 5.1 使用实际模型服务手动验证 QA 与 Agent 的 token 流、Agent 工具状态、新闻引用、停止生成、认证失败和供应商中断；验证不输出思维链、工具参数或敏感原始数据。
- [x] 5.2 运行后端全量 `pytest`、前端 `npm run build` 与 `openspec validate add-streaming-ai-responses --strict`；验证全部通过并记录任何外部依赖的已知警告。
