## Context

现有 `NewsRetrievalService` 通过 `NewsSearchPort` 对 `news` 表执行关键词匹配，`POST /api/ai/qa` 和 Agent 的新闻知识工具都复用该抽象。当前 Docker Compose 的 `redis:7-alpine` 只提供普通 Redis 缓存能力，不能满足 Redis 向量索引和既有 LangGraph Redis checkpointer 对 RediSearch 的要求。

项目已在 `app/embedding/bge-large-zh-v1.5` 保存本地 `bge-large-zh-v1.5` 模型。该模型输出 1024 维向量、最大输入长度为 512；现有新闻正文较短，因此本阶段可以每篇新闻建立一条向量文档。动机和对外行为见 [proposal.md](proposal.md) 与本 Change 的 delta specs。

## Goals / Non-Goals

**Goals:**

- 在本机通过 Docker Compose 启动可被宿主机 FastAPI 调用的 TEI 服务，并挂载本地模型为只读数据。
- 以 Redis Stack 持久化新闻向量并提供相似度检索，同时与普通缓存和 Agent checkpoint 隔离。
- 让 QA 与 Agent 无需变更 API 契约即可共享“语义优先、关键词兜底”的检索结果。
- 让索引构建可显式、幂等地重复执行，适合本项目当前以批量导入新闻为主的开发方式。

**Non-Goals:**

- 不实现新闻切块、多向量文档、实时增量索引、后台队列或管理端 UI。
- 不替换 LLM 供应商、不增加 SSE、不新增 Agent 工具，也不改变收藏/浏览历史工具。
- 不把本地模型文件加入 Git，不在应用启动时自动执行全量重建。

## Decisions

### 使用本地 TEI 作为 Embedding 服务

Docker Compose 新增 `embedding` 服务，使用包含 TEI 1.8 队列溢出修复的 `ghcr.io/huggingface/text-embeddings-inference:cpu-1.9`，将 `./app/embedding/bge-large-zh-v1.5` 挂载到容器内模型路径并设置 `MODEL_ID`。本机运行 FastAPI 时通过 `http://127.0.0.1:8081` 访问该服务；将来 FastAPI 容器化时改用 Compose 服务名和容器端口。

CPU 开发环境初始采用保守的并发和批处理限制（`MAX_CONCURRENT_REQUESTS=4`、`MAX_CLIENT_BATCH_SIZE=4`、`MAX_BATCH_TOKENS=4096`），并使用模型本身的最大长度配合 TEI 自动截断，避免本地 CPU 被一次全量索引耗尽。Embedding 服务 URL、模型名、请求超时、批量大小、向量检索数量及相似度阈值均由服务端配置加载。

备选方案是进程内直接加载 `sentence-transformers`。不采用它，因为会增加 FastAPI 进程内存、启动时间和模型生命周期复杂度，也无法自然演进为独立推理服务。

### 将 Redis 升级为 Redis Stack，并隔离用途

Compose 中的 Redis 镜像改为带 RediSearch 的 `redis/redis-stack-server`。保留 6379 端口、持久化卷和 `redis-cli ping` 健康检查，使用镜像支持的 Redis 参数启用 AOF。应用继续使用 Redis DB 0，但约定独立命名空间：既有缓存、LangGraph checkpoint 与新闻向量索引分别拥有不重叠的前缀和索引名。

不为新闻向量另启 Redis 实例：当前数据规模小，共用一个 Redis Stack 能复用运行维护、同时解决 checkpointer 的 RediSearch 依赖。隔离前缀及索引名可避免清理/重建新闻索引时触及会话或缓存。若未来向量负载显著增长，再拆分为专用实例而不改变检索端口。

### 每篇新闻建立一个 1024 维向量文档

索引文本由新闻标题、简介和正文按固定顺序拼接；向量文档保存 `news_id`、标题、简介、正文/受限摘录和浏览量等生成引用所需的字段。Redis 向量索引以模型的 1024 维输出为准，查询采用 KNN 相似度并限制返回数量。

当前新闻内容长度适合单文档模型，能让引用保持新闻粒度且简化索引同步。备选的分块索引更适合长文，但会增加去重、合并引用和更新/删除复杂度，留到文章长度和语料规模增长后再引入。

### 引入复合检索端口，保留关键词实现作为可靠降级

保留 `NewsSearchPort` 作为 QA/Agent 已依赖的稳定抽象。新增语义检索适配器和组合实现：优先调用 Embedding + Redis 向量查询；只有在 TEI、Redis 向量索引或索引数据不可用时，才调用既有 SQL 关键词检索。语义命中为空但服务健康时直接返回空结果，不混入关键词结果，避免模糊的排序语义。

两个路径都转换为同一 `RetrievedArticle` 形状；向量命中生成安全的短摘录，关键词路径保留当前确定性摘录。QA 与 Agent 继续只依赖该统一结果，因此 API 请求、响应、引用格式和 Agent 工具名称不变。

备选方案是在 QA 和 Agent 中分别直接调用向量库。不采用它，因为会重复故障处理和引用转换，并破坏已有的可替换检索边界。

### 采用显式、幂等的全量重建入口

新增受控的管理命令/CLI：从 `news` 表按批读取当前新闻，批量请求 TEI 并按稳定的 `news_id` 写入专属向量命名空间。每次全量重建清理或覆盖该专属命名空间，使被删除或变更的新闻不会残留为可检索文档；整个过程绝不操作非新闻向量的键或索引。

不在 HTTP 请求路径和应用启动钩子自动重建，避免用户请求被长时间模型任务阻塞，也避免在数据库或 Redis 暂不可用时拉低应用启动可靠性。内容写入端未来增加后，再由独立 Change 设计增量同步。

## Risks / Trade-offs

- [本地 CPU 的 TEI 吞吐有限] → 采用受配置控制的批量大小和并发；重建命令输出进度及失败项，并在开发部署文档中说明首次建索引耗时。
- [TEI 或 Redis Stack 未启动] → 组合检索记录可诊断日志并降级到 SQL 关键词检索，不将基础设施异常泄露给前端或模型。
- [Redis 内存增长] → 当前每新闻单向量、限制召回数量；配置 Redis 持久化卷，并在重建时仅维护新闻专属命名空间。
- [模型替换导致维度不兼容] → 向量维度、模型名和索引版本由配置显式控制；变更模型时通过新索引版本和全量重建完成迁移。
- [本地模型文件过大] → 将 `app/embedding/` 添加到 Git 忽略规则；Compose 仅挂载运行时已有文件，仓库不承载模型二进制。

## Migration Plan

1. 将 Compose Redis 服务替换为 Redis Stack，并增加 TEI 服务；保留现有 Redis 数据卷和端口映射。
2. 配置本地 Embedding 服务地址和新闻向量索引命名空间，启动依赖服务并验证 Redis Stack 的搜索模块和 TEI 健康状态。
3. 部署应用的检索适配器与全量重建命令；先执行单元/集成测试，再对现有新闻运行一次显式全量索引。
4. 验证 QA 与 Agent 的语义查询、无匹配查询、TEI 不可用和 Redis 索引不可用场景，确认均遵循 delta specs。
5. 回滚时恢复普通 Redis 镜像或停用语义配置；应用自动沿用 SQL 关键词检索。新闻专属向量键可单独清理，不影响缓存与 checkpoint。
