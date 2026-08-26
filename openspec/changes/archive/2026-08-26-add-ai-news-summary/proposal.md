## Why

The application currently serves news records but cannot provide an AI-generated digest, so users must read an entire article to understand its key points. Adding an authenticated news-summary capability establishes the first backend-owned AI workflow while caching repeat requests to control latency and model-call cost.

## What Changes

- Add an authenticated API that generates a concise summary for one existing news article.
- Add a backend LLM client abstraction configured exclusively through server-side environment variables; no model-provider credential is exposed to the frontend.
- Cache successful summaries in Redis using a key derived from the news identity and its summarizable content version.
- Return an explicit cache-status indicator so clients and operators can distinguish generated and cached summaries.
- Define safe failure behavior for missing news, unavailable Redis, and unavailable model providers.
- Add automated tests for cache-hit, cache-miss, invalidation, and error paths.

## Capabilities

### New Capabilities

- `ai-news-summary`: Generate, cache, and retrieve an authenticated AI summary for a news article.

### Modified Capabilities

- None.

## Impact

- Affected backend areas: `app/api/routers`, `app/ai/summarization`, `app/core/config.py`, `app/cache`, and tests.
- Adds a server-side LLM SDK/provider dependency and environment configuration for the selected model.
- Uses the existing MySQL `news` data and Redis service; does not alter the existing news-list cache contract.
- Adds a new frontend-facing API endpoint and requires the frontend to call the backend rather than a model provider directly for summaries.
