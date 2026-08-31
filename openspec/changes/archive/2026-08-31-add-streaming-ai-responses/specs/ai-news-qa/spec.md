## ADDED Requirements

### Requirement: 已认证的流式新闻问答

系统 SHALL 向已认证用户提供 `POST /api/ai/qa/stream`，接受与现有新闻问答相同的非空问题并以 SSE 返回回答。该接口 MUST 保持与现有 QA 相同的新闻检索、来源约束和供应商凭据保护；现有 `POST /api/ai/qa` JSON 接口 SHALL 保持可用且契约不变。

#### Scenario: 流式输出基于新闻的回答

- **WHEN** 已认证用户以有效问题调用 `POST /api/ai/qa/stream` 且找到支持新闻
- **THEN** 系统先后发送可见回答增量与可信新闻引用，并以成功完成事件结束

#### Scenario: 没有相关新闻时流式拒答

- **WHEN** 已认证用户调用流式 QA 但没有找到支持新闻
- **THEN** 系统发送基于来源约束的拒答文本和空引用，并以成功完成事件结束且不调用模型供应商

#### Scenario: 流式 QA 认证或校验失败

- **WHEN** 请求没有有效 Bearer Token 或问题为空
- **THEN** 系统在启动 SSE 前返回既有认证或校验错误，且不会调用检索或模型供应商

#### Scenario: 流式 QA 供应商失败

- **WHEN** SSE 已开始后模型供应商失败、超时或返回不可用输出
- **THEN** 系统发送安全错误事件并结束流，不返回虚构引用或成功完成事件
