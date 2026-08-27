# FastAPI AI Agent News Backend

An async news backend built with FastAPI, SQLAlchemy, MySQL, Redis, and Pydantic. The project includes user authentication, news categories and lists, favorites, browsing history, and Redis caching for frequently accessed news data. The database schema also reserves tables for related-news recommendations and AI chat records.

## Requirements

- Python 3.14+
- Docker Desktop with Docker Compose
- `uv`

## Configuration

Copy the environment template and set the MySQL password:

```powershell
Copy-Item .env.example .env
```

Edit `.env`:

```env
MYSQL_PASSWORD=your_mysql_password
```

The application reads MySQL, Redis, and AI settings from `app/core/config.py`. Do not commit `.env`.

### AI news summary

AI summary credentials are server-side settings. Add the following values only to the root `.env`; never expose `LLM_API_KEY` in `Front-end/.env` or browser code.

```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=your-server-only-ai-api-key
LLM_MODEL=your-summary-model
LLM_TIMEOUT_SECONDS=30
AI_SUMMARY_MAX_CHARACTERS=400
AI_SUMMARY_CACHE_TTL_SECONDS=2592000
```

After logging in, request a summary for an article with:

```http
POST /api/ai/news/{news_id}/summary
Authorization: Bearer <application-token>
```

The response data contains `newsId`, `summary`, and `cacheStatus`. `miss` means the backend generated and cached a new summary; `hit` means Redis returned a summary for the current news content; `unavailable` means the model returned a summary but Redis could not be used. Cache keys include a hash of the title and body, so edited news never reuses an old summary.

### AI news question answering (RAG)

Ask questions grounded in the news database through the backend:

```http
POST /api/ai/qa
Authorization: Bearer <application-token>
Content-Type: application/json

{ "question": "有哪些关于 AI 的新闻？" }
```

The response `data` contains `answer` and `citations`. Each citation includes `newsId`, `title`, and `excerpt` from an article used to ground the answer. The backend searches Redis Stack vectors first, then falls back to a MySQL keyword search only when the local Embedding service or vector index is unavailable. A healthy semantic search with no match returns no citation rather than mixing in unrelated keyword results.

All model provider credentials stay server-side. The browser only sends the application bearer token and the question; it never stores or sends an LLM API key. The frontend AI chat page now calls `/api/ai/qa` rather than a provider endpoint directly.

## Start MySQL, Redis Stack, and Embedding

```powershell
docker compose up -d
```

This starts:

- MySQL on `localhost:3306`
- Redis Stack (Redis + RediSearch) on `localhost:6379`
- Local Text Embeddings Inference (TEI) on `localhost:8081`

Before starting TEI, put the locally downloaded `bge-large-zh-v1.5` model in `app/embedding/bge-large-zh-v1.5`. This directory is intentionally ignored by Git, so each developer must prepare it locally and must not commit model binaries.

Check that all services are healthy before starting the API:

```powershell
docker compose ps
docker exec toutiao-redis redis-cli FT._LIST
Invoke-WebRequest http://127.0.0.1:8081/health
```

If port `6379` or `8081` is occupied, set `REDIS_PORT` or `EMBEDDING_PORT` before `docker compose up -d`, and make the matching change in the backend `.env`. The application must connect to Redis Stack rather than a standard Redis server, because vector retrieval and the Agent checkpointer require RediSearch.

### Build the semantic news index

After MySQL, Redis Stack, and TEI are healthy, build the vectors explicitly:

```powershell
uv run python -m app.ai.rag.reindex
```

The command reads every current `news` row in configured batches and replaces only the `ai:news:vector:v1:` keys. It is safe to repeat after importing, editing, or deleting news: cache keys and Agent checkpoint keys are not cleared. With the default CPU configuration, the initial build can take a few minutes.

The default TEI image is pinned to `cpu-1.9`, with batches capped at four documents. If TEI is unhealthy, first confirm the model directory and `docker compose logs embedding`; the backend will continue to answer through keyword retrieval until the semantic dependency is restored. To roll back semantic retrieval temporarily, stop the `embedding` service or point `EMBEDDING_BASE_URL` at an unavailable endpoint; no API contract changes are needed because the keyword fallback remains active.

## Build the database tables

The complete schema and seed data are in [`database/database.sql`](database/database.sql). It creates the `news_app` database and these tables:

- `user` and `user_token`
- `news_category` and `news`
- `related_news`
- `favorite`
- `history`
- `ai_chat`

After MySQL is healthy, import the SQL file into the container:

```powershell
docker cp database/database.sql toutiao-mysql:/tmp/database.sql
docker exec -i toutiao-mysql sh -c 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" < /tmp/database.sql'
```

The SQL file includes initial categories, news, and a test user. Run the import once for a fresh database. Re-running it may attempt to insert the seed data again.

## Start the API

```powershell
uv sync
uv run uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`. Interactive API documentation is available at `/docs`.

## Project structure

```text
app/
  main.py              FastAPI application entry point
  api/routers/         HTTP route handlers
  core/                Settings, database, Redis, auth, responses, exceptions
  models/              SQLAlchemy ORM models
  schemas/             Pydantic request and response models
  services/            Current news, user, favorite, and history logic
  cache/               Redis cache key and serialization helpers
  ai/
    summarization/     Cached, server-side AI news summary generation
    embeddings/        Embedding and semantic retrieval
    rag/               Retrieval-augmented generation
    agent/             Agent orchestration and tool calling
    streaming/          SSE and other streaming responses
database/              MySQL schema and seed data
Front-end/             Vue/Vite client application
tests/                 Configuration tests
```

## Cache behavior

News list reads use a cache-aside flow:

1. Build a cache key from category, page, and page size.
2. Return the cached JSON data when available.
3. Query MySQL on a cache miss.
4. Serialize the result and store it in Redis with a TTL.

Redis is treated as an optimization. If Redis is unavailable, the API falls back to MySQL for cache reads and writes.

## Front-end

```powershell
cd Front-end
npm install
npm run dev
```

The browser client runs on the Vite development server, normally `http://localhost:5173`.

The AI news-summary button in the news-detail page calls the backend endpoint and sends only the application's bearer token. Its model-provider credential remains in the root backend `.env`.

