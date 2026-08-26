# Project Roadmap

> 本文件用于跨 Change 导航。详细需求、设计与任务保留在各自的 OpenSpec Change 中。

## Initiative

- **Goal:** 将现有 FastAPI 新闻系统逐步演进为具备摘要、RAG 问答、Agent 工具调用、语义检索和流式交互能力的 AI 新闻应用。
- **Success:** 已认证用户能够获得可缓存的新闻摘要、带引用的新闻问答，并通过 Agent 安全调用新闻业务工具；检索层支持语义召回，RAG 与 Agent 响应支持 SSE 流式输出。
- **Non-goals:** 本轮规划不包含多 Agent 协作、浏览器直连模型供应商、无人监督的高风险外部操作或生产级模型评测平台。

## Progress

- **Current Phase:** Phase 3 — News Agent Tools
- **Next Change:** `add-news-agent-tools`
- **Completed:** 2 / 5

## Phases

### Phase 1 — AI News Summary

- [x] `add-ai-news-summary`
- **Outcome:** 用户可以在新闻详情页获取由后端生成并由 Redis 缓存的新闻摘要。
- **Boundary:** 仅处理单篇新闻摘要；不包含跨新闻检索、问答、Agent 或流式输出。
- **Depends on:** None.
- **Verify:** 相同内容的重复摘要请求命中缓存，新闻内容变化后重新生成，并正确处理 Redis 与模型故障。

### Phase 2 — RAG News QA

- [x] `add-rag-news-qa`
- **Outcome:** 用户可以基于新闻库进行带来源引用的非流式问答。
- **Boundary:** 使用关键词检索；不包含 Embedding、向量检索、Agent 工具调用或 SSE。
- **Depends on:** `add-ai-news-summary`.
- **Verify:** 问题命中新闻时返回基于来源的回答与引用，无相关资料时拒答且不伪造引用。

### Phase 3 — News Agent Tools

- [ ] `add-news-agent-tools`
- **Outcome:** 用户可以通过 Agent 调用新闻详情、收藏、浏览历史和 RAG 问答等受控业务工具。
- **Boundary:** 复用现有关键词 RAG 与业务服务；不引入向量检索、Embedding 或 SSE。
- **Depends on:** `add-rag-news-qa`.
- **Verify:** Agent 能依据用户意图选择正确工具，在已认证用户边界内执行，并返回可追溯结果。

### Phase 4 — Semantic News Retrieval

- [ ] `add-news-semantic-retrieval`
- **Outcome:** RAG 内部检索层使用新闻 Embedding 和向量相似度获得更强的语义召回能力。
- **Boundary:** 只替换和增强检索层；不改变现有 RAG/Agent 对外契约，也不增加流式输出。
- **Depends on:** `add-rag-news-qa`.
- **Verify:** 自然语言问题能够召回语义相关但关键词不完全重合的新闻，并保持 RAG 与 Agent 既有行为通过回归验证。

### Phase 5 — Streaming AI Responses

- [ ] `add-streaming-ai-responses`
- **Outcome:** RAG 与 Agent 可以通过 SSE 增量返回生成结果和必要的执行状态。
- **Boundary:** 只增强响应传输与交互体验；不新增检索策略或 Agent 业务工具。
- **Depends on:** `add-news-agent-tools`, `add-news-semantic-retrieval`.
- **Verify:** 客户端在完整回答生成前持续收到有序事件，并能正确处理完成、错误与连接中断。

## Cross-Cutting Constraints

- 模型供应商凭据只保存在后端环境配置中，浏览器不得持有或发送供应商 API Key。
- Agent 工具必须继承当前认证用户上下文，收藏和浏览历史等用户数据不得跨用户访问。
- RAG 与 Agent 依赖稳定的检索抽象，使关键词检索能够在后续被语义检索替换而不改变调用方契约。
- 每个 Phase 必须作为独立 Change 完成验证并归档后，才在本 Roadmap 中标记为完成。
- 每个 Phase 完成规范同步、归档和 Roadmap 状态核对后，必须创建一个独立 Git 检查点提交；默认不自动推送远程仓库。
