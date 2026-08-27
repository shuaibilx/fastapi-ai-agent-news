## 1. 运行时依赖与配置边界

- [x] 1.1 在 `pyproject.toml` 中添加与现有供应商适配器兼容的顶层 LangChain Agent 依赖并更新锁文件，运行 `uv sync` 及 Agent 核心导入检查确认依赖可用
- [x] 1.2 在 `app/core/config.py`、根 `.env.example` 和相关配置测试中加入历史轮数、历史 Token、工具结果、总输入、TTL 与最大执行轮次配置，运行配置测试验证默认值和非法范围校验

## 2. 有界会话记忆

- [x] 2.1 先为会话轮次、UUID 会话标识和 `TokenBudgetPolicy` 编写失败测试，覆盖最多五轮、从最旧完整问答对裁剪、当前消息优先及当前消息仍超限时拒绝
- [x] 2.2 实现 Agent 会话 DTO、会话标识生成/校验和 Token 预算策略，运行 2.1 的测试确认轮数与上下文预算行为通过
- [x] 2.3 先为 `ConversationMemoryStore` 编写失败测试，覆盖用户与会话组合键、Redis List 原子追加/裁剪、滑动 TTL、过期空历史及读写异常状态
- [x] 2.4 实现 Redis `ConversationMemoryStore`，仅保存成功的用户消息与最终助手回答，并运行 2.3 的测试确认五轮持久化和 `empty`/`loaded`/`unavailable` 状态通过

## 3. 只读业务工具

- [x] 3.1 先为四个 Agent 工具编写失败测试，覆盖新闻检索、新闻详情、当前用户收藏、当前用户历史、分页/结果上限、无结果和禁止模型传入 `user_id`
- [x] 3.2 实现类型化 Agent 运行时上下文、只读 DTO 与 `search_news_knowledge`、`get_news_detail`、`list_my_favorites`、`list_my_history` 工具，运行 3.1 的测试验证工具只访问认证用户范围且不返回 ORM 内部字段
- [x] 3.3 为工具结果的模型可见内容、应用侧引用元数据、工具执行摘要和大小裁剪补充测试与实现，验证新闻引用可确定性去重且敏感运行时信息不进入响应

## 4. Agent 编排服务

- [x] 4.1 先使用假聊天模型或可注入 Agent runner 编写失败测试，覆盖无需工具、单工具、多工具、错误工具选择边界、最大执行轮次、供应商失败以及失败轮次不写入记忆
- [x] 4.2 在 `app/ai/agent` 中实现 LangChain `create_agent` 工厂、系统提示词、固定工具注册和模型调用前上下文预算中间件，运行 Agent 工厂测试确认工具 schema 不包含 `user_id` 且执行轮次受限
- [x] 4.3 实现 Agent 应用服务，串联历史加载、当前消息、运行时上下文、工具轨迹、引用收集和成功轮次保存，运行 4.1 的测试确认 `loaded`/`empty`/`unavailable` 降级及错误映射通过

## 5. 后端 API 契约

- [x] 5.1 先为 `POST /api/ai/agent` 编写 API 失败测试，覆盖认证、空消息、可选/复用 `conversationId`、响应字段、Redis 降级、供应商 503 和超预算请求
- [x] 5.2 在 `app/schemas/ai.py` 与 `app/api/routers/ai.py` 中加入 Agent 请求响应模型、依赖装配和错误映射，运行 5.1 的 API 测试确认统一响应包含回答、会话标识、引用、工具摘要与记忆状态
- [x] 5.3 运行现有 `ai-news-qa`、摘要及认证相关回归测试，确认新增 Agent 没有改变 `POST /api/ai/qa` 和既有 AI 接口行为

## 6. 前端 Agent 对话体验

- [x] 6.1 在 `Front-end/src/api/ai.js` 增加 Agent 请求封装并更新 `AIChat.vue` 使用 `POST /api/ai/agent`，运行前端构建确认请求只携带 Bearer Token、消息和可选 `conversationId`
- [x] 6.2 在 `AIChat.vue` 中保存服务端返回的当前会话标识、提供“新对话”重置行为，并展示引用、工具摘要和记忆不可用提示，运行前端构建并手动验证连续六轮对话仍能正常交互

## 7. 集成验证

- [x] 7.1 运行完整后端测试套件与前端生产构建，使用测试替身验证收藏/历史跨用户隔离、五轮裁剪、多工具组合、Redis 故障降级和 Agent 执行上限
- [x] 7.2 运行 `openspec validate add-news-agent-tools --strict` 并核对 Git diff，确认实现仅包含只读 Agent、轻量 Redis 短期记忆和前端接入，没有提前引入向量检索、写入工具或 SSE
