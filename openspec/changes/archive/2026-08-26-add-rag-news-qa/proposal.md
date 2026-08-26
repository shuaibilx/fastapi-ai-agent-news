## Why

The application currently has no way for a user to ask questions and receive grounded answers from the news database; the only AI chat page calls an external model directly from the browser, exposing provider credentials and bypassing the backend. Adding a backend-owned retrieval-augmented news QA capability makes answers factual, auditable, and safe while establishing the foundation for later Agent and streaming features.

## What Changes

- Add a backend-only RAG news QA endpoint that accepts a user question and returns an answer with supporting news citations.
- Add server-side retrieval from the existing `news` table using keyword-based search first; vector-based semantic retrieval remains a later Change.
- Add a source-grounded prompt that instructs the model to answer only from retrieved news context and to decline when no relevant source exists.
- Add citation metadata for every answer, including news IDs, titles, and the matched excerpts that support the answer.
- Add server-side chat settings and provider configuration; the browser never holds or sends an LLM API key.
- **BREAKING** Remove the frontend AI chat page's direct calls to `https://api.deepseek.com/chat/completions` and browser-side provider credentials; this page is no longer a supported direct-model chat UI.
- Add automated tests for retrieval, answer generation, citation completeness, refusal when no context is found, provider failure handling, and authentication.

## Capabilities

### New Capabilities

- `ai-news-qa`: Backend-owned retrieval-augmented question answering over the news database with citations.

### Modified Capabilities

- None. The existing `ai-news-summary` capability remains unchanged.

## Impact

- Affected backend areas: `app/ai/rag`, `app/api/routers/ai.py`, `app/schemas/ai.py`, `app/services/news.py`, `app/core/config.py`, and tests.
- Affected frontend area: `Front-end/src/views/AIChat.vue`, `Front-end/src/config/api.js`, and route definitions that reference direct provider chat; the direct-model chat page is removed or replaced by a backend-driven entry point.
- Dependencies and systems: Uses the existing MySQL `news` table and the existing Redis cache connection; no new vector database or embedding provider is introduced in this Change.
- Provider model settings continue to be server-side environment variables only; no provider key is exposed to the browser.
