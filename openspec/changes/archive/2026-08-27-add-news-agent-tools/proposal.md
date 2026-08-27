## Why

现有新闻问答只能沿固定的“检索后回答”链路运行，无法根据用户意图组合新闻详情、个人收藏、浏览历史和新闻知识检索。下一阶段需要引入一个受认证边界保护的只读 Agent，让用户可以用自然语言完成跨业务信息查询，同时为后续语义检索和 SSE 流式输出保留稳定接口。

## What Changes

- 新增已认证的非流式新闻 Agent 接口，由 LangChain Agent 根据用户意图选择受控的只读工具并生成最终回答。
- 提供新闻知识检索、新闻详情、当前用户收藏列表和当前用户浏览历史四类只读工具；新闻知识检索复用现有关键词检索层，不把完整 `QaService` 嵌套为 Agent 工具。
- 由服务端运行时注入可信 `user_id` 和数据库会话，模型及客户端不能指定其他用户身份。
- Agent 响应返回最终回答、新闻引用和已执行工具的可追溯摘要，同时保留现有 `POST /api/ai/qa` 直接问答接口。
- 使用现有 Redis 保存按用户和会话隔离的短期记忆：最多五个完整问答轮次，并同时受历史 Token 预算和滑动 TTL 限制。
- 当前 Redis 不可用时将 Agent 降级为无记忆调用；模型或核心 Agent 执行失败时返回明确的服务不可用响应。
- 更新前端 AI 对话页以使用 Agent 接口、维护 `conversationId`，并展示引用与工具执行信息。
- 本 Change 不包含写入型工具、多 Agent、Embedding、向量检索或 SSE 流式输出。

## Capabilities

### New Capabilities

- `ai-news-agent`: 定义已认证新闻 Agent 的请求响应、只读工具选择、用户数据隔离、来源引用和故障语义。
- `ai-agent-conversation-memory`: 定义按用户与会话隔离、最多五轮且受 Token 预算和 TTL 约束的 Redis 短期对话记忆。

### Modified Capabilities

无。现有 `ai-news-qa` 的外部行为保持不变；Agent 仅复用其检索抽象，不修改直接 QA 接口的需求契约。

## Impact

- 后端新增或扩展 `app/ai/agent`，并复用 `app/ai/rag` 与 `app/services` 中的现有读取能力。
- `app/api/routers/ai.py` 与 `app/schemas/ai.py` 将新增 Agent 依赖装配、请求和响应模型。
- `app/core/config.py` 将新增工具结果、历史轮数、Token 预算和记忆 TTL 等可配置限制；`app/core/cache.py` 的 Redis 客户端继续作为缓存基础设施。
- Python 依赖将补充 LangChain Agent 所需的顶层 `langchain`/LangGraph 运行时能力，并继续使用现有 OpenAI-compatible 模型适配器。
- `Front-end/src/api/ai.js` 和 `Front-end/src/views/AIChat.vue` 将切换到 Agent API，并管理会话标识与结果展示。
- 测试范围扩展到工具选择、用户隔离、引用映射、五轮记忆裁剪、Token 上限、Redis 降级和供应商故障。
