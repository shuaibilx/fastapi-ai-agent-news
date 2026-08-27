## 1. 运行依赖与配置

- [x] 1.1 将 `docker-compose.yml` 的 Redis 服务升级为 Redis Stack Server，并新增只读挂载 `app/embedding/bge-large-zh-v1.5` 的本地 TEI `embedding` 服务；验证 `docker compose config` 成功且两个服务均通过健康检查。
- [x] 1.2 为 Embedding URL、模型名、超时、批量大小、索引名称/前缀、向量维度、召回数量和相似度阈值增加服务端配置，并将本地模型目录加入 Git 忽略规则；验证配置缺省值可加载且 `git status` 不列出模型二进制。
- [x] 1.3 增加 Redis 向量检索及 HTTP Embedding 所需的 Python 依赖；验证依赖同步完成并能导入相应模块。

## 2. 向量索引与全量构建

- [x] 2.1 先编写 Embedding 客户端与 Redis 向量索引适配器的失败测试，覆盖批量向量化、1024 维校验、稳定新闻 ID、命名空间隔离和基础设施错误的受控转换；验证新增测试在实现前失败。
- [x] 2.2 实现本地 TEI Embedding 客户端和 Redis Stack 向量索引适配器，保存生成引用所需的新闻元数据；验证 2.1 的单元测试通过。
- [x] 2.3 实现显式的全量新闻索引重建命令，按批读取 `news` 表并仅清理/覆盖新闻向量专属命名空间；验证在隔离 Redis Stack 中首次和重复运行后均为每篇当前新闻保留一条记录，且缓存/checkpoint 键未受影响。

## 3. 统一检索与现有功能集成

- [x] 3.1 先为复合检索服务编写失败测试，覆盖近义查询的向量优先结果、健康但无命中的空结果、TEI/索引不可用时的关键词降级及有界引用数据；验证测试在实现前失败。
- [x] 3.2 实现语义优先、关键词降级的 `NewsSearchPort` 组合适配器，并统一两条路径的 `RetrievedArticle` 结果；验证 3.1 的单元测试通过。
- [x] 3.3 将 QA 服务和 Agent 新闻知识工具装配到统一检索服务，保持 `POST /api/ai/qa`、`POST /api/ai/agent` 的请求/响应契约和工具名称不变；验证现有 QA/Agent 回归测试及新增语义检索场景通过。

## 4. 端到端验证与运维说明

- [x] 4.1 在隔离的 Redis Stack 与 TEI 实例上执行全量重建并进行语义查询，验证近义问题能返回真实新闻引用、无结果不产生虚构引用、关闭 TEI 或向量索引后仍可关键词降级。
- [x] 4.2 更新项目运行说明，记录 Docker 启动顺序、索引重建命令、模型目录准备方式、常见故障和回滚方式；验证全新开发环境可据此启动依赖并完成一次索引构建。
- [x] 4.3 运行 `pytest` 全量测试与 `openspec validate add-news-semantic-retrieval --strict`；验证所有测试通过且 Change 规范校验成功。
