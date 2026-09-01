## 1. 依赖与配置边界

- [x] 1.1 添加 `langchain-text-splitters` 与轻量 BGE tokenizer 运行依赖并更新锁文件，执行项目依赖同步及导入烟雾测试确认 Python 3.14 环境可安装使用
- [x] 1.2 增加 Chunk 大小、重叠、Embedding 输入上限、候选 Chunk 数、每篇新闻片段上限、上下文 token 预算、v2 Index Alias 与 tokenizer 路径配置，使用 Settings 测试验证默认值、环境变量和 `overlap < chunk_size < embedding_limit <= 512` 等交叉约束

## 2. 中文新闻分块

- [x] 2.1 定义可追溯 Chunk 领域模型与文本清洗规则，覆盖 `news_id`、确定性 `chunk_id`、顺序、字符位置、原始片段和内容哈希，并以重复输入产生完全相同结果的单元测试验证确定性
- [x] 2.2 实现使用 BGE tokenizer 计数的中文递归分块器，按自然段、换行、句子和子句边界切分并提供有界重叠，使用长正文、中文标点、跨边界事实和短新闻单 Chunk 测试验证行为
- [x] 2.3 构造有界 `embedding_text`，在每个 Chunk 使用受限标题前缀、仅在首块加入简介并保留原始 `chunk_text`，使用 tokenizer 断言每个 Embedding 输入不超过配置硬上限且不依赖 TEI 截断

## 3. v2 Chunk 向量存储

- [x] 3.1 将 Redis 向量文档和搜索命中模型升级为 Chunk Schema，保存 `news_id`、Chunk 身份、顺序、位置、引用元数据和 FLOAT32 Embedding，并用 Redis 命令模拟测试验证 HNSW Schema、字段解析和 1024 维校验
- [x] 3.2 实现按 `build_id` 隔离的 Key 前缀、具体 Index 与活动 Alias 操作，使用存储层测试验证候选构建不会覆盖新闻缓存、摘要缓存或 Agent Checkpoint 命名空间
- [x] 3.3 实现仅针对明确 v2 build 的受控清理与保留策略，使用测试证明失败清理和旧 build 清理不会删除活动 Alias 所指数据或宽泛匹配其他 Redis Key

## 4. 安全的全量索引构建

- [x] 4.1 重构索引构建器为“读取新闻 → 生成多个 Chunk → 分批调用 TEI → 写入候选索引”，输出扫描新闻数、生成 Chunk 数和写入 Chunk 数，并以多 Chunk 新闻及 Embedding 数量不匹配测试验证一一映射
- [x] 4.2 在候选索引完成后校验文档数量、向量维度和代表性查询，再通过 `FT.ALIASADD`/`FT.ALIASUPDATE` 激活；使用故障注入测试验证 TEI、Redis 写入或校验失败时活动读取入口保持不变
- [x] 4.3 更新索引构建 CLI 的输出、退出码和回退提示，使用命令测试验证成功构建可报告 build 信息、失败构建返回非零且不会宣称切换成功

## 5. Chunk 召回、聚合与上下文

- [x] 5.1 将向量查询改为召回配置数量的 Chunk 候选并进行相似度过滤，使用测试验证候选上限独立于最终新闻上限、分数计算正确且低分 Chunk 被过滤
- [x] 5.2 实现按 `news_id` 聚合、每篇新闻片段限额、新闻最高 Chunk 分数排序和稳定去重，使用“同一新闻占据多数候选”的测试验证最终仍可保留其他相关新闻且每篇不超过配置上限
- [x] 5.3 扩展检索结果以同时携带模型使用的完整命中 `passages` 和客户端展示的最高分 `excerpt`，使用测试验证引用来自命中 Chunk 而非正文开头
- [x] 5.4 实现共享的 token 预算上下文组装与重叠消除，使用超预算和相邻 Chunk 测试验证只纳入完整可追溯片段、总量不超过 `AI_QA_MAX_CONTEXT_TOKENS` 且不重复重叠文本
- [x] 5.5 将 Chunk 聚合结果接入非流式/流式 QA 和 Agent `search_news_knowledge` 工具，使用 API 与工具测试验证现有响应结构、SSE 引用事件和关键词降级保持兼容

## 6. 评测、迁移与文档

- [x] 6.1 建立包含正文 512 tokens 之后事实、跨边界事实、同新闻多片段、多新闻近似主题及无关问题的标注检索样本，并运行评测脚本输出 `Recall@20`、`MRR`、`HitRate@5`、上下文精确度和引用正确性
- [x] 6.2 对候选 `chunk_size`、overlap 和最低分阈值执行可重复的小规模参数比较，将选定默认值及评测结果记录到 Change 验证说明，确认最终默认值不是直接沿用未经验证的 v1 分数分布
- [x] 6.3 更新 `.env.example`、README 和运维命令，说明 v2 构建、Alias 切换、监控、回退及精确清理流程，并按文档在隔离 Redis Stack 与 TEI 环境完成一次 v1 保留、v2 构建、切换和回退演练

## 7. 完整验证

- [x] 7.1 运行 Chunk、向量存储、索引构建、检索聚合、QA、Agent 与 API 定向测试，确认长正文后部事实可被召回且真实命中片段进入模型上下文和客户端引用
- [x] 7.2 运行完整 pytest、`openspec validate improve-news-vector-chunking --strict` 和差异检查，确认无既有测试回归、OpenSpec 严格校验通过且未修改本 Change 范围外的缓存与会话行为
