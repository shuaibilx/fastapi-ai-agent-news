## MODIFIED Requirements

### Requirement: 复用可替换的新闻检索能力

新闻知识工具 SHALL 复用现有新闻检索抽象，优先使用语义检索并在该能力暂时不可用或没有可用索引时降级为关键词检索。工具 SHALL 返回有界的新闻片段与引用元数据，而 MUST NOT 通过嵌套调用完整新闻 QA 生成流程来产生工具结果。现有 `POST /api/ai/qa` 接口 SHALL 继续独立可用且行为保持不变。

#### Scenario: Agent 检索到新闻资料

- **WHEN** 新闻知识工具通过语义检索或关键词降级找到与问题相关的新闻
- **THEN** 工具向 Agent 提供有界上下文，并提供由系统生成的新闻 ID、标题和摘录元数据

#### Scenario: Agent 检索降级

- **WHEN** 新闻知识工具的语义检索能力暂时不可用或没有可用索引
- **THEN** 工具使用关键词检索继续查询，且不向 Agent 或客户端暴露向量基础设施堆栈错误

#### Scenario: Agent 检索不到新闻资料

- **WHEN** 新闻知识工具没有找到相关新闻
- **THEN** Agent 明确说明没有足够新闻资料，且不伪造引用

#### Scenario: 直接 QA 继续工作

- **WHEN** 客户端调用现有 `POST /api/ai/qa`
- **THEN** 系统继续按照 `ai-news-qa` 契约执行固定的检索增强问答
