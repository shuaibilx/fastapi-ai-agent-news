## Context

见 `proposal.md` 的 Why。当前 `build_news_embedding_text()` 将整篇新闻拼接后调用 TEI；本地 `BGE-large-zh-v1.5` 的 `max_seq_length` 为 512，部署又启用了 `--auto-truncate`，因此超长正文后部不会形成可检索表示。Redis v1 Schema 以 `news_id` 作为唯一文档身份，检索层随后把正文开头 80 个字符映射为 `excerpt`，QA 和 Agent 实际使用的上下文与向量命中位置脱节。

现有 QA 与 Agent 共用 `NewsRetrievalService`，这是统一升级检索行为的边界。Redis Stack、TEI、关键词降级和现有 HTTP 响应模型继续保留；`AI_QA_MAX_CONTEXT_CHARS` 当前未参与上下文构造，需要由真正生效的 token 预算替代。

## Goals / Non-Goals

**Goals:**

- 生成确定、可重复、符合 BGE 输入上限的中文新闻 Chunk。
- 让索引记录、检索命中、模型上下文和客户端引用指向同一正文片段。
- 在扩大 Chunk 候选召回后按新闻聚合，兼顾相关片段覆盖和新闻来源多样性。
- 使用独立 v2 索引完成无损构建、验证、切换和回退。
- 通过长正文与标注查询评测分块参数和相似度阈值，而不是把经验值当作最终结论。

**Non-Goals:**

- 本 Change 不引入 Cross-Encoder Reranker、BM25/向量混合排序或 LLM 语义分块。
- 本 Change 不实现 CDC、消息队列或新闻变更后的实时增量索引；仍保留受控全量构建入口。
- 本 Change 不改变 QA、Agent 的 HTTP 路径、顶层响应结构或关键词降级语义。
- 本 Change 不把派生 Chunk 持久化到 MySQL；Redis 向量索引仍可由 `news` 表完整重建。

## Decisions

### 1. 使用中文结构优先、BGE token-aware 的递归分块

新增独立 `NewsChunker` 领域组件，使用 `langchain-text-splitters` 的 `RecursiveCharacterTextSplitter` 组织递归边界，并通过本地 BGE `tokenizer.json` 的实际 tokenizer 作为 `length_function`。分隔优先级为自然段、换行、`。！？；`、`，、`，最后才允许硬切分。

初始配置采用正文目标 `320 tokens`、重叠 `48 tokens`、完整 Embedding 输入硬上限 `480 tokens`；保留 512 上限中的余量给特殊 token 和标题前缀。标题在每个正文 Chunk 中以有界前缀出现，简介只并入首个 Chunk；短新闻在总预算内只生成一个 Chunk。切分输出包含 `chunk_index`、`start_index`、`end_index`、原始 `chunk_text` 和内容哈希。

选择该方案是因为它能确定性复现、适合新闻自然结构且成本可控。固定字符切分不能可靠约束 BGE token；LLM/Embedding 语义断点切分会增加构建成本和不确定性，留待有评测证据后再考虑。

### 2. 将 Embedding 输入与可引用原文分离

每个向量文档同时保存：

- 用于 Embedding 的 `embedding_text`，由有界标题前缀、首块可选简介和正文片段组成；
- 用于 QA/Agent 与客户端引用的原始 `chunk_text`；
- `news_id`、`chunk_id`、`chunk_index`、位置、标题、分类、发布时间、内容哈希等元数据。

这样标题可为每个片段补充主题，但不会让前端引用出现重复前缀，也不会再通过完整 `content` 字段把整篇正文送入检索结果。

### 3. 使用隔离的 v2 构建命名空间和 Redis Search Alias

每次全量构建生成唯一 `build_id`：

```text
Key prefix: ai:news:chunk:v2:{build_id}:
Document:   ai:news:chunk:v2:{build_id}:{news_id}:{chunk_index}
Index:      idx:ai:news:chunk:v2:{build_id}
Alias:      idx:ai:news:chunk:active
```

构建器先创建候选索引并批量写入 Chunk，核对扫描新闻数、生成 Chunk 数、写入数和可查询性后，才通过 `FT.ALIASADD`/`FT.ALIASUPDATE` 切换读取。失败候选仅清理自己的 build 命名空间，不触碰当前 Alias 指向的索引。旧 v1 索引和上一个有效 v2 build 在回退窗口内保留，再由显式维护命令清理。

相比原地 `clear_documents()` 后重写，此方案避免构建中断导致线上索引只剩部分新闻；代价是迁移和重建期间会短时占用两份向量内存。

### 4. 区分 Chunk 候选量与最终新闻量

初始检索参数为：

```text
candidate_chunk_limit = 20
final_news_limit = 5
max_chunks_per_news = 2
minimum_score = 0.35（仅作为待评测初值）
```

HNSW 先返回 Chunk 候选并做最低分过滤，再按 `news_id` 分组。新闻分数取其最高 Chunk 分数；组内按分数选取最多两个 Chunk，最终上下文按新闻分数、Chunk 顺序稳定排列。相邻 Chunk 的重叠内容在组装时去重，不额外扩大单篇新闻配额。

这能避免 Top-5 Chunk 全部来自同一篇新闻，同时保留同一新闻中至多两个互补事实片段。后续如加入 Reranker，应建立在候选 Chunk 集之上，不能替代本次分块与聚合。

### 5. 模型上下文与客户端 excerpt 使用不同长度边界

`RetrievedArticle` 演进为可携带完整 `passages` 和展示用 `excerpt` 的聚合结果：模型上下文使用预算内的完整命中 Chunk；客户端 `excerpt` 从最高分 Chunk 截取有界展示文本。QA 与 Agent 共享同一个上下文组装器，避免各自重新截取正文。

新增 `AI_QA_MAX_CONTEXT_TOKENS`，初值 `2400`；上下文组装按相关性逐项装入，任何单个 Chunk 超预算时不从中间任意截断，而是跳过或使用可追溯的完整较小片段。现有 Agent 工具结果仍受 `AI_AGENT_TOOL_RESULT_MAX_TOKENS` 的第二层总预算保护。

### 6. 参数通过检索评测校准

建立包含“事实位于 512 tokens 之后、跨边界事实、同新闻多片段、多新闻近似主题、无关问题”的标注样本。对 `chunk_size`、overlap、候选数和阈值执行小规模网格比较，至少记录 `Recall@20`、`MRR`、最终新闻 `HitRate@5`、上下文精确度与引用正确性。

初始参数用于实现和回归测试，最终阈值必须依据 Chunk 分数分布确定；不能直接假设整篇新闻索引使用的 `0.35` 在 Chunk 索引上仍然最优。

## Risks / Trade-offs

- [Chunk 数量增加导致 Redis 内存和构建时间上升] → 配置 Chunk 大小与重叠，输出构建统计，并在切换前检查预估记录数和 Redis 可用容量。
- [重复标题导致不同 Chunk 向量过于相似] → 限制标题 token，仅在 `embedding_text` 使用，并通过新闻级聚合限制单篇占用。
- [重叠导致模型上下文重复] → 保存 Chunk 顺序和位置，在上下文组装时消除可识别的重叠区间。
- [tokenizer 与 TEI 实际模型不一致] → tokenizer 路径与 Embedding 模型配置绑定，启动和构建时校验最大长度及特殊 token 行为。
- [Alias 切换后新代码解析异常] → 切换前执行真实查询烟雾测试，保留上一个有效 build 与 v1 索引，并提供显式回退配置。
- [相似度阈值迁移后误召回或漏召回] → 将阈值保持可配置，使用标注查询评测后再固化推荐默认值。

## Migration Plan

1. 添加 Chunker、v2 Schema、配置和单元测试，但保持线上读取 v1。
2. 在独立 build 命名空间构建 v2 索引，验证新闻覆盖率、Chunk 数、向量维度和代表性长正文查询。
3. 部署支持 v2 聚合结果的 QA/Agent 代码，先通过配置或测试环境读取 v2 Alias。
4. 完成检索质量和 API 兼容验收后，将生产读取切换到 `idx:ai:news:chunk:active`。
5. 观察错误率、关键词降级率、检索延迟和无结果比例；异常时恢复旧应用配置继续读取 v1，或将 Alias 回退到上一个兼容 v2 build。
6. 回退窗口结束后，通过显式维护命令清理旧 build；不得使用宽泛 Key 匹配删除新闻缓存或 Agent Checkpoint。
