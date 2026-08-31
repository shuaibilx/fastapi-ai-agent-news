## Context

当前 `GET /api/news/list` 使用 `categoryId`、页码和页大小构成固定 TTL 的 Redis 列表缓存，但总数仍每次查询 MySQL，且查询没有显式排序。新闻或分类的应用内写路径尚未集中；直接 SQL 或导入也不会通知缓存。详见 proposal.md 的 Why。

## Goals / Non-Goals

**Goals:**

- 在新闻列表成员、排序或分类归属已提交变更后，使受影响分类的所有旧分页缓存立即不再参与读取。
- 保持公开接口字段兼容，并保证 `list`、`total`、`hasMore` 来自同一分页快照。
- 让 Redis 继续只是优化层：缓存操作失败不阻断新闻读取或已提交的数据库写入。
- 给未来新闻/分类管理、数据导入和批量修复提供统一失效边界。

**Non-Goals:**

- 不新增新闻或分类管理 HTTP API；本 Change 只提供这些写路径必须调用的缓存协调能力。
- 不实现新闻向量索引的增量更新、Embedding 重算、RAG/Agent 回答缓存或通用消息队列。
- 不保证列表浏览量实时一致；浏览量采用 TTL 范围内最终一致。
- 不尝试自动监听任意直接 SQL；受控运维操作必须显式调用失效入口。

## Decisions

### 使用分类世代 Key 失效分页缓存

每个分类维护 `news:cache:category:{category_id}:generation`。读取先取得当前 generation，再读取：

```text
news:list:v2:{category_id}:g{generation}:p{page}:s{page_size}
```

新闻新增、删除、迁移分类，或更改影响排序/成员的字段时，在 MySQL commit 成功后递增相关分类的 generation。旧 Key 不扫描、不逐页删除，依靠既有 TTL 回收。全量/未分类列表（若未来开放）使用独立 global generation。

选择 generation 而不是 `SCAN + DEL`：分页数未知，模糊扫描在生产 Redis 中延迟不可预测，也容易遗漏不同页大小的 Key。generation 一次递增可覆盖所有历史分页和页大小。

### 固定排序并缓存完整分页响应

新闻列表统一使用 `publish_time DESC, id DESC` 作为确定性排序。缓存值改为包含 `list`、`total` 与 `hasMore` 的 JSON 响应快照；路由不再额外查询总数。

选择单响应快照而非分别缓存列表与总数：避免列表来自旧缓存、总数来自新数据库的矛盾响应。列表为空也缓存完整快照，使用独立的较短 TTL。

### 分类缓存采用独立世代与查询形状

分类维护 `news:cache:categories:generation`，数据键包含 generation 和实际查询参数；实现可选择只由路由调用“完整分类列表”并限制服务层不缓存任意切片。分类写入提交后递增该世代。

### 写后失效的调用顺序

业务写入必须遵循：

```text
验证输入 → MySQL transaction/commit → 递增 Redis generation → 返回成功
```

数据库提交失败时不改变 generation。Redis 失效失败不回滚已提交数据库事务：记录结构化日志并让 Redis 不可用时的读取回源 MySQL。为避免 Redis 恢复后保留已知旧 generation，提供可重试的受控运维失效入口；后续可靠异步重试/Outbox 可作为独立演进，不在本 Change 引入后台 Worker。

### 浏览量采用最终一致而非全页失效

详情阅读会高频更新 `views`。该字段不会递增分类 generation，列表和列表中的浏览量可在普通 TTL 内暂时滞后。标题、正文、发布时间、分类和上下架/删除等改变新闻可见集合或排序的字段必须失效。

### 缓存保护与可观测性

- 正常缓存 TTL 使用配置基值加有界随机抖动；空分页采用更短独立 TTL。
- 读取与写入将缓存异常降级为数据库路径，并记录 cache hit、miss、read/write/invalidation failure 的结构化日志或指标钩子。
- 未来可为热点 Key 加互斥重建；本 Change 先保留可扩展接口，不引入分布式锁，以避免把未验证的并发等待语义加入读取关键路径。

## Risks / Trade-offs

- [Redis 在 commit 后失效失败，恢复后仍存在旧 generation] → 记录失败并提供受控重试/全量新闻缓存失效入口；部署或导入完成后执行该入口。后续以独立 Change 引入持久化 Outbox 提升自动恢复能力。
- [直接 SQL 绕过应用写边界] → 在导入文档和管理流程中要求调用运维失效入口；不承诺自动感知任意外部数据库变更。
- [generation 造成旧 Key 短时间共存] → 保留 TTL 回收；generation Key 与数据 Key 使用 `v2` 命名空间，避免与旧缓存混淆。
- [浏览量允许短暂滞后] → 明确为列表页最终一致字段；详情页继续直接读取数据库最新值。
- [并发 miss 仍可能同时回源] → 用日志/指标确认热点后再引入 singleflight 或 Redis 锁，避免过早增加锁故障模式。

## Migration Plan

1. 发布包含 generation 读取和 `v2` 数据 Key 的代码；新键不读取旧 `news_list:*` 值。
2. 部署后执行受控新闻/分类缓存失效入口，确保当前 generation 可用。
3. 观察缓存命中、Redis 错误和数据库列表查询量；旧 Key 按 TTL 自然回收。
4. 回滚时恢复旧读取逻辑；`v2` Key 不影响数据库或其他 Redis 命名空间。

## Open Questions

- 暂无。本 Change 按“应用写路径受控、直接 SQL 后执行运维失效入口”的约束设计；如果未来需要自动处理外部数据源，应通过独立的 Outbox/CDC Change 决定可靠同步机制。
