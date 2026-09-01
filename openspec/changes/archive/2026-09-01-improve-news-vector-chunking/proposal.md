## Why

当前新闻语义索引将“标题 + 简介 + 完整正文”压缩为单个向量；长正文超过 `BGE-large-zh-v1.5` 的 512 token 上限后会被 TEI 截断，正文后部事实无法被检索，整篇向量也会稀释局部语义。现有检索随后仅把正文开头的短片段交给 QA 和 Agent，不能保证生成上下文与实际命中的语义片段一致。

## What Changes

- 将新闻正文改为面向中文标点和自然段的 token-aware 递归分块，为每个 Chunk 独立生成 Embedding，并确保任何 Embedding 输入不依赖 TEI 自动截断。
- 使用 v2 Chunk 文档模型和独立 Redis 索引命名空间，保存可追溯的 `news_id`、`chunk_id`、顺序、正文片段、位置及引用元数据。
- 将检索流程改为“Chunk 候选召回 → 相似度过滤 → 新闻级去重与片段聚合 → 上下文预算裁剪”，避免候选被同一新闻垄断。
- 让 QA、Agent 和前端引用使用真正命中的正文片段，而不是固定截取新闻正文开头。
- 提供可重复、可验证、可回退的 v1 到 v2 索引构建与切换路径，并补充长正文、边界事实、重复 Chunk 和无关问题的检索测试。
- 将分块大小、重叠、候选 Chunk 数、每篇新闻片段上限和上下文预算配置化；现有相似度阈值在 Chunk 数据上重新校准。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `news-semantic-retrieval`: 将单新闻向量检索升级为可追溯的 Chunk 级索引、新闻级聚合和受 Token 预算约束的 RAG 上下文构造。

## Impact

- 影响 `app/ai/rag/` 中的索引构建、向量文档、Redis Search Schema、召回映射和 QA 上下文构造。
- 影响 Agent 的 `search_news_knowledge` 工具结果以及 QA/Agent 引用中的 `excerpt` 来源，但不改变现有 HTTP 路径和顶层响应结构。
- 新增中文递归分块与 BGE tokenizer 计数所需依赖和配置；Redis Stack、TEI 与 MySQL 的部署边界保持不变。
- 需要创建 v2 Key 前缀和索引，验证完成后切换读取；v1 索引在回退窗口内保留，避免原地覆盖导致服务中断。
