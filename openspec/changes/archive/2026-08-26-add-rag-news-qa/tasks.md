## 1. Backend Configuration and Retrieval

- [x] 1.1 Add server-side QA settings to `app/core/config.py` for provider model reuse, retrieval result limit, and provider timeout; document them in root `.env.example`.
- [x] 1.2 Implement a keyword retrieval service that searches `news` title, description, and content and returns bounded, relevance-ordered article context.
- [x] 1.3 Implement deterministic excerpt extraction for each retrieved article so citations contain one or more matched excerpts.

## 2. RAG Gateway and Service

- [x] 2.1 Add `app/ai/rag` with a source-grounded QA prompt instructing the model to answer only from retrieved context and refuse when context is insufficient.
- [x] 2.2 Build a QA gateway on the existing server-side OpenAI-compatible LangChain pattern with timeout and provider-error translation.
- [x] 2.3 Implement the QA orchestration service: retrieve first, return a refusal answer when no news matches, otherwise generate an answer with citations derived from retrieval results.

## 3. API and Schema

- [x] 3.1 Add Pydantic QA request/response schemas with answer, citations (news ID, title, excerpts), and server-side error semantics.
- [x] 3.2 Add `POST /api/ai/qa` to `app/api/routers/ai.py`, using the existing authentication dependency and standard response envelope.
- [x] 3.3 Ensure empty questions fail validation without calling the provider, missing/invalid auth returns the standard error, and provider failures return service-unavailable.

## 4. Frontend Legacy Removal

- [x] 4.1 Replace direct `https://api.deepseek.com/chat/completions` usage in `Front-end/src/config/api.js` and `AIChat.vue` so the browser never calls a provider or holds an LLM API key.
- [x] 4.2 Remove `VITE_AI_API_KEY` usage and document that AI provider credentials are backend-only; update `Front-end/.env.example` accordingly.
- [x] 4.3 Update frontend routing/UI to expose the backend QA contract without the old direct-model chat page.

## 5. Automated Verification

- [x] 5.1 Add unit tests for keyword retrieval ordering, excerpt extraction, refusal on no matches, and bounded result counts.
- [x] 5.2 Add service tests with a fake QA gateway covering answer generation, citation completeness, empty-question rejection, provider timeout, and refusal behavior.
- [x] 5.3 Add API tests for authentication enforcement, successful QA response schema, empty-question validation, and service-unavailable provider failures.
- [x] 5.4 Run the full backend test suite and ensure the frontend production build still succeeds after removing direct-provider code.

## 6. Documentation

- [x] 6.1 Update README with the `/api/ai/qa` request/response contract, retrieval/citation behavior, and the rule that model provider keys belong only on the backend.
- [x] 6.2 Confirm the archived `ai-news-summary` capability and its Redis cache remain unchanged and passing.

