## Context

The backend already exposes news read APIs, reads `News` through asynchronous SQLAlchemy sessions, and has a shared asynchronous Redis client. Redis helpers currently collapse cache misses and connection failures into the same `None` result, which is insufficient for the required cache-status response. The frontend contains an AI chat view, but AI provider access must move behind the backend before summary features are exposed. See `proposal.md` for the motivation and `specs/ai-news-summary/spec.md` for the behavior contract.

## Goals / Non-Goals

**Goals:**

- Add a backend-owned, authenticated, single-news summary workflow with a stable response contract.
- Keep model-provider configuration and credentials entirely on the server.
- Reuse Redis for summaries without coupling this feature to the existing news-list cache implementation.
- Make cache hits, cache misses, and Redis unavailability observable to the API consumer and application logs.
- Establish an LLM adapter that later RAG and Agent changes can reuse without exposing provider-specific calls throughout the application.

**Non-Goals:**

- Streaming tokens, multi-turn chat, RAG, Embedding generation, and vector retrieval.
- Persisting summaries in MySQL or adding a new database table.
- Summarizing arbitrary user-provided text or URLs.
- Adding model-provider keys to browser environment files or implementing frontend chat changes beyond a summary API client.
- Guaranteeing deduplication of simultaneous cache-miss requests; distributed request coalescing can be added after real traffic requires it.

## Decisions

### 1. Create a dedicated AI summary API and response schema

Add `POST /api/ai/news/{news_id}/summary`, protected by the existing current-user dependency. Its success payload will use the existing application response envelope and contain `newsId`, `summary`, and camel-case `cacheStatus` (`hit`, `miss`, or `unavailable`).

The request is a `POST` because a cache miss can invoke a paid, potentially slow model operation; it is not a side-effect-free read even though a later identical request can be served from cache. The route will live in an AI router rather than the existing `news` router so subsequent RAG and Agent endpoints have a clear API boundary.

Alternative considered: add a `GET /api/news/detail` field or a `GET /summary` endpoint. This would hide model work inside an existing read API and make latency, failure, and cost behavior ambiguous, so it is rejected.

### 2. Introduce an LLM gateway behind a narrow service interface

Implement the feature under `app/ai/summarization/`, separating prompt construction, provider invocation, and orchestration. Use LangChain's OpenAI-compatible chat-model integration so `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, and `LLM_TIMEOUT_SECONDS` are server-side settings. The gateway returns only validated summary text and converts provider timeout/transport/provider errors into a domain-level unavailable error.

The first prompt will constrain output to concise factual Chinese prose based only on the supplied news title and content. It will not include user data or client-provided provider instructions.

Alternative considered: call a provider SDK directly inside the route. This is simpler initially but couples API code to one provider and would need to be rewritten for RAG and Agent work, so it is rejected.

### 3. Version cache entries by summarizable article content

Cache successful results as JSON at a key shaped like `ai:summary:v1:{news_id}:{content_hash}`, where `content_hash` is a deterministic SHA-256 digest of the article title and content. The cache value stores the summary and generation metadata needed by the API; the expiration is controlled by `AI_SUMMARY_CACHE_TTL_SECONDS` and defaults to 30 days.

When the title or content changes, a new hash produces a cache miss and a new summary. Old keys expire naturally; no synchronous scan/delete is required. Cache serialization and key construction will be owned by a summary-specific cache module rather than the existing generic news-list cache helpers.

Alternative considered: use only `news_id` as the key and delete cache entries in every news-update path. That approach is vulnerable to missed invalidation paths and expands this change into unrelated news-write workflows, so it is rejected.

### 4. Make Redis degradation explicit and non-fatal

Summary-cache reads and writes will return a structured outcome that distinguishes `hit`, `miss`, and connection/serialization failure. On a cache failure, the orchestration service will call the LLM and return the generated result with `cacheStatus: unavailable`; it will log the cache failure but will not label an uncached result as a hit or miss.

If the provider fails, the endpoint returns the application's service-unavailable response and never stores empty or partial text. Missing news is checked before cache or model access.

Alternative considered: fail every summary request when Redis is unavailable. Redis is an optimization for this feature, not the source of truth, so that would unnecessarily remove a useful capability.

### 5. Validate the model output before caching it

The summary service will trim model output and reject blank output before returning or caching it. The first implementation will use one bounded summary-length configuration to prevent unexpectedly large responses; model output that fails validation is treated as a provider failure.

Alternative considered: cache every raw model response. That would allow malformed and blank answers to persist for the full TTL, so it is rejected.

## Risks / Trade-offs

- [Provider latency or rate limits make the endpoint slow] → Configure a finite timeout, return a clear 503-style failure, and rely on cache hits to reduce repeat calls.
- [Redis currently masks failures as cache misses] → Add summary-specific cache outcomes and tests; do not reuse a `None` value as evidence of a normal miss.
- [A content-versioned key leaves old cache entries until expiry] → Use a bounded TTL and key version prefix; this avoids fragile invalidation scans.
- [LLM output can hallucinate or ignore length guidance] → Use a restrictive source-grounded prompt, validate non-empty bounded output, and defer factual citations to the later RAG change.
- [Parallel cache misses can generate duplicate summaries] → Accept this limited initial trade-off and add a Redis lock only if metrics show duplicate provider calls are material.
- [Frontend environment files may still contain legacy provider configuration] → Remove the provider API key from client usage as part of this Change and verify the summary request contract does not accept it.

## Migration Plan

1. Add server-only LLM settings and document placeholder values in `.env.example`; do not commit a real key.
2. Add the dependency, AI route, summary service, summary schemas, and summary-specific Redis cache module behind the new endpoint.
3. Add automated unit and API tests using a fake LLM gateway and controllable cache outcomes; run them before enabling the UI integration.
4. Add the frontend summary client only after the backend contract passes tests. Existing news APIs and existing news-list cache keys remain unchanged.
5. Deploy with the endpoint disabled by missing provider configuration until a valid server-side key is supplied. Roll back by removing the AI router from application registration; cached Redis keys are namespaced and can safely expire without affecting existing cache data.

## Open Questions

- The exact provider and model deployment remain configurable through the OpenAI-compatible gateway and do not change the API contract. Select the initial production model when configuring the deployment environment.
