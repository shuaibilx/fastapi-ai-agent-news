## 1. AI Runtime Configuration

- [x] 1.1 Add the LangChain OpenAI-compatible model dependency and server-only LLM settings for base URL, API key, model, timeout, maximum summary length, and summary cache TTL.
- [x] 1.2 Document placeholder AI settings in the root `.env.example` and confirm real provider credentials remain excluded by `.gitignore`.
- [x] 1.3 Create the AI router/module boundary and register it in `app.main` without changing existing news routes.

## 2. Summary Domain and Cache

- [x] 2.1 Define Pydantic request/response/domain schemas for a validated summary result and the `hit`/`miss`/`unavailable` cache-status values.
- [x] 2.2 Implement the summary-specific Redis cache module with JSON serialization, the `ai:summary:v1:{news_id}:{content_hash}` key format, configurable TTL, and structured cache outcomes.
- [x] 2.3 Implement deterministic content hashing from a news article's title and body, ensuring changed source content cannot reuse a prior summary.
- [x] 2.4 Implement the LangChain-backed summary gateway, source-grounded Chinese prompt, timeout/error translation, and non-empty bounded-output validation.
- [x] 2.5 Implement the summary orchestration service: load news first, read cache, invoke the gateway only on miss/unavailability, cache only complete successful output, and surface dependency outcomes correctly.

## 3. API and Frontend Integration

- [x] 3.1 Implement `POST /api/ai/news/{news_id}/summary` using the existing authentication dependency and standard response/error conventions.
- [x] 3.2 Ensure missing news short-circuits before Redis or LLM access, Redis outages return a generated `unavailable` result when possible, and model failures return a service-unavailable error.
- [x] 3.3 Add a frontend summary API client and integrate an explicit summary action in `Front-end/src/views/NewsDetail.vue` that displays loading, summary, cache state, and request errors without using a browser-side provider key.
- [x] 3.4 Remove any summary-related direct model-provider request or credential use from browser-delivered frontend code.

## 4. Automated Verification

- [x] 4.1 Add unit tests for content-hash stability, cache key/version construction, cache JSON handling, and cache failure outcomes.
- [x] 4.2 Add service tests with fake news repositories, cache outcomes, and LLM gateway to cover cache hit, cache miss, content change, missing news, Redis unavailability, provider timeout, and blank model output.
- [x] 4.3 Add API tests for authentication enforcement, successful response schema, 404 missing news, and service-unavailable provider failures.
- [x] 4.4 Run backend tests and the frontend production build; manually verify that a second unchanged summary request returns `cacheStatus: hit` without an additional model call.

## 5. Operational Documentation

- [x] 5.1 Update the README with AI summary prerequisites, environment configuration, endpoint usage, Redis cache behavior, and the rule that provider keys belong only on the backend.
