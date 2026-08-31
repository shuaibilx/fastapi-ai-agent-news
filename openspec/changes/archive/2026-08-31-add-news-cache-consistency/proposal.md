## Why

新闻分类和分页列表目前只依赖固定 TTL 缓存。新闻新增、删除、改分类或改变排序字段后，已缓存的页码可能继续返回旧内容，且分页偏移会使后续页面整体错位；空结果也会反复访问数据库。需要在保留 Redis 故障回源能力的前提下，让缓存随已提交的新闻业务变更立即失效。

## What Changes

- 为新闻列表定义稳定、可预测的数据库排序规则，保证分页和缓存键对应同一结果集。
- 引入按分类维护的缓存版本（generation），将版本纳入新闻分页列表缓存 Key；新闻写入提交成功后递增受影响分类的版本，使所有旧分页缓存立即不可读而由 TTL 回收。
- 将列表、总数和 `hasMore` 作为同一版本的分页缓存响应，避免列表来自缓存而总数来自不同数据库时刻。
- 为新闻分类引入可失效的版本化缓存，并使缓存 Key 与查询形状保持一致。
- 缓存空分页结果并采用较短 TTL；为正常缓存 TTL 增加受控随机抖动，降低穿透和集中失效风险。
- 建立新闻缓存失效服务边界；未来新增、更新、删除或迁移新闻分类的写路径必须在数据库成功提交后调用该边界。
- 保持 Redis 不可用时的 MySQL 回源行为，并记录缓存读取、写入或失效失败以便诊断。

## Capabilities

### New Capabilities

- `news-cache-consistency`: 为新闻分类和分页列表提供与已提交新闻数据变更一致的版本化 Cache-Aside 缓存。

### Modified Capabilities

- 无。

## Impact

- 受影响代码：`app/services/news.py`、`app/cache/news_cache.py`、`app/api/routers/news.py`、Redis 缓存封装、新闻写入服务以及对应测试。
- API：现有 `GET /api/news/categories` 与 `GET /api/news/list` 的成功响应字段保持兼容；列表读取将使用稳定排序和同版本的列表/总数快照。
- Redis：新增新闻列表和分类的版本键、带版本号的数据键与短 TTL 空结果键；既有旧 Key 通过 TTL 自然过期。
- 不包含：新闻向量索引增量同步、Embedding 重算、Transactional Outbox Worker、Agent/RAG 最终回答缓存或用户私有收藏/历史缓存。
