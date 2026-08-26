## Context

The backend already owns server-side LLM configuration and an OpenAI-compatible LangChain gateway used for single-article summaries (`app/ai/summarization`). The `news` table stores title, description, content, and category for each article. The frontend currently contains a direct-browser chat page that calls `https://api.deepseek.com/chat/completions` with a client-side key, bypassing the backend. See `proposal.md` for the motivation and `specs/ai-news-qa/spec.md` for the behavior contract.

## Goals / Non-Goals

**Goals:**

- Provide an authenticated backend endpoint that answers news questions from retrieved article context.
- Base answers on retrieved `news` records and return citations with news IDs, titles, and matched excerpts.
- Keep all LLM credentials server-side and remove the browser-side direct model call.
- Start with keyword search over the existing `news` table, without introducing a vector database or embedding provider.
- Reuse the existing server-side OpenAI-compatible gateway pattern without coupling to a particular provider.
- Preserve the archived `ai-news-summary` capability and its Redis summary cache.

**Non-Goals:**

- Adding semantic/vector retrieval or an embedding database (later Change).
- Adding Agent tool orchestration or multi-tool selection (later Change).
- Streaming tokens via SSE for QA (later Change).
- Multi-turn conversation memory or chat-history persistence.
- Building a new full chat UI; this Change removes the insecure direct-model page and exposes a backend QA contract.

## Decisions

### 1. Expose a dedicated `POST /api/ai/qa` endpoint

The new route lives in the existing AI router under `app/api/routers/ai.py`, protected by the same current-user dependency used by summary. The request body is a non-empty question; the response uses the existing `success_response` envelope and includes `answer` plus `citations` metadata.

Alternative considered: extend the existing non-streaming summary endpoint. That would overload a single-article cache endpoint with full-corpus QA, so a dedicated endpoint is preferred.

### 2. Implement keyword retrieval over the `news` table

Implement a service function that tokenizes the user question and queries `news` rows using `LIKE`/`ILIKE`-style matching against `title`, `description`, and `content`. The query SHOULD prioritize rows with more matches and limit results to a configured maximum (for example, the top 5). This avoids adding a vector dependency in this Change while producing a bounded context window.

Alternative considered: full-text index on MySQL `news`. That is a valid later optimization and may require schema/migration work; the initial implementation uses straightforward matching to remain self-contained and testable.

### 3. Build a source-grounded RAG prompt and gateway

Add `app/ai/rag` containing a retrieval service and a QA gateway built on the same `ChatOpenAI`/LangChain pattern as the summary gateway. The prompt includes the retrieved article excerpts and instructs the model to answer only from that context and to refuse when the context is insufficient. This is the core grounding boundary.

Alternative considered: calling the provider directly inside the router. Reusing a gateway keeps provider errors, timeouts, and credential handling centralized and lets later Agent/streaming work build on the same boundary.

### 4. Return explicit citations with every answer

The response schema contains an answer string and a citations array with `newsId`, `title`, and `excerpt(s)`. Citations are derived from retrieval results, not from model output, so a fabricated citation cannot be introduced by the model. If retrieval returns no articles, the service returns a refusal answer with an empty citations array instead of invoking the model.

Alternative considered: asking the model to output citation IDs. This risks hallucinated or unstable identifiers, so it is rejected.

### 5. Remove direct model access from the frontend

Delete or neuter the `aiChatConfig` provider endpoint and API-key flow in `Front-end/src/config/api.js`, and update `AIChat.vue`/routing so the frontend no longer calls `api.deepseek.com`. The frontend will use the backend QA endpoint with only the application bearer token. Because the frontend deliverable is an API contract in this Change, a full replacement chat view is explicitly out of scope and left to the later Agent/UI phase.

Alternative considered: keeping the direct page while adding the backend endpoint alongside it. That would leave an insecure browser-key path in the shipped app, so the legacy direct path is removed.

## Risks / Trade-offs

- [Keyword retrieval can produce noisy or low-quality context] → Keep the domain grounded prompt, cap retrieved rows, sort by match relevance, and replace this layer with semantic retrieval in the next Change.
- [Model may still hallucinate despite grounding] → Use strong system instructions, include only retrieved context, and return refusal when context is empty; do not rely on model-supplied citations.
- [Removing the existing chat page may surface UI gaps] → This Change defines the backend contract and disables the insecure direct path; a proper AI chat/Agent surface is delivered by the later Agent/UI Change.
- [MySQL LIKE scans can become expensive on large corpora] → Bound result count and candidate matching; introduce full-text or vector search in a later Change.
- [Provider failure could block the QA feature] → Return a clear service-unavailable response and log the provider error; no partial or ungrounded answer is produced.

## Migration Plan

1. Add server-side QA settings (for example, maximum result count and timeout) to `app/core/config.py`; all provider values stay in root `.env` only.
2. Add the keyword retrieval service and RAG gateway under `app/ai/rag`.
3. Add request/response schemas for QA and the new `POST /api/ai/qa` route, protected by the existing auth dependency.
4. Add unit/API tests for retrieval, citations, refusal, auth, and provider failure before enabling the UI change.
5. Replace the direct-model frontend code and remove `VITE_AI_API_KEY` usage from `Front-end/.env.example`/`api.js`.
6. Deploy requires only the existing MySQL and Redis services; no migration/rollback of stored data is needed. Rollback is removing the AI router registration or reversing the frontend API file change.

## Open Questions

- The exact keyword matching and relevance scoring strategy can be tuned during implementation without changing the API contract; the later semantic-retrieval Change will replace this layer.
