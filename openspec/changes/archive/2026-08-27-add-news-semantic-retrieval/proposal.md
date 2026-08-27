## Why

当前新闻问答与 Agent 的新闻知识工具仅依赖关键词检索，用户换用近义表达或概念性提问时容易找不到相关报道；同时，已具备本地中文 Embedding 模型，适合在不引入外部模型依赖的前提下升级为语义检索。本阶段建立可重复构建的新闻向量索引，并保持服务在向量组件暂时不可用时仍能通过现有关键词检索回答。

## What Changes

- 在 Docker Compose 中增加本地 Hugging Face Text Embeddings Inference（TEI）服务，加载项目内的 `bge-large-zh-v1.5` 模型。
- 将现有 Redis 容器升级为带 RediSearch 模块的 Redis Stack Server，为 LangGraph checkpoint 与新闻向量索引提供同一个 Redis 服务；不同索引与键前缀相互隔离。
- 新增新闻 Embedding 生成、Redis 向量索引读写和可重复执行的全量重建能力；每篇当前新闻对应一个向量文档。
- 将新闻检索抽象改为“语义检索优先、关键词检索降级”，使现有 `POST /api/ai/qa` 和 Agent 新闻知识工具在不变更请求与响应契约的前提下复用该能力。
- 当 TEI、Redis 向量索引或索引数据不可用时，自动使用关键词检索；两种检索都无结果时继续返回现有的无法基于新闻回答语义。

## Capabilities

### New Capabilities

- `news-semantic-retrieval`: 对新闻生成向量、维护 Redis 向量索引、执行语义召回并提供受控降级的内部检索能力。

### Modified Capabilities

- `ai-news-qa`: 新闻问答的新闻来源检索从仅关键词匹配升级为语义优先并保留关键词降级。
- `ai-news-agent`: Agent 的新闻知识工具复用语义优先、关键词降级的检索实现，外部工具与 API 契约保持不变。

## Impact

- 影响 `docker-compose.yml`、应用配置、AI 检索适配层、新闻问答服务、Agent 新闻工具及其测试。
- 新增本地 TEI 服务和 Redis Stack Server 运行依赖，并增加与 Redis 向量检索集成所需的 Python 依赖。
- 不新增前端接口、不改变现有 QA 或 Agent 接口的请求/响应格式；不会在本阶段实现 SSE、新闻分块、增量写入钩子或新的 Agent 工具。
