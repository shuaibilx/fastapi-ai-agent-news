## Automated verification

- `uv sync`: completed; tokenizer and text-splitter imports succeed on Python 3.14.
- `python -m pytest -q` with the real Redis Stack/TEI integration enabled: 159 passed, 2 infrastructure-gated tests skipped, 4 subtests passed.
- `python -m compileall -q app tests`: passed.
- `git diff --check`: passed.
- Labeled fixture and metric implementation tests: passed. The tail-fact label begins after 512 BGE tokens.

## Real BGE parameter evaluation

The labeled fixture covers a fact after BGE token 512, a cross-boundary fact, multiple passages from one article, similar news topics, and an irrelevant question. The 27-combination grid was run against the local `bge-large-zh-v1.5` TEI service and written to `evaluation-results.json`.

For the selected `chunk_size=320` and `overlap=48`:

| Minimum score | Recall@20 | MRR | HitRate@5 | Context precision | Citation correctness | Irrelevant rejection |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0.25 | 1.00 | 1.00 | 1.00 | 0.5625 | 0.4333 | 1.00 |
| 0.35 | 1.00 | 1.00 | 1.00 | 0.8750 | 0.6250 | 1.00 |
| 0.45 | 1.00 | 1.00 | 1.00 | 1.0000 | 1.0000 | 1.00 |

The selected defaults are `chunk_size=320`, `overlap=48`, `candidate_chunks=20`, `max_chunks_per_news=2`, and `minimum_score=0.45`. The Chunk settings preserve sentence/paragraph coherence while leaving headroom below the 512-token BGE input limit. The calibrated threshold rejects lower-quality passages in this labeled set without reducing candidate recall. This is a project baseline, not a claim that the small fixture replaces production traffic evaluation.

Reproduce the grid with:

```powershell
uv run python -m app.ai.rag.evaluate --output openspec/changes/improve-news-vector-chunking/evaluation-results.json
```

## Redis Stack, TEI, switch, and rollback rehearsal

The rehearsal used Redis Stack `redis/redis-stack-server:7.4.0-v8` on port 6380, TEI `cpu-1.9` on port 8081, and 403 MySQL news rows.

- Initial active build: `idx:ai:news:chunk:v2:20260901T034459Z-27b4ab19`, 403 documents.
- Second isolated build: `idx:ai:news:chunk:v2:20260901T061954Z-4d8aa158`, 403 documents.
- Alias switch: `idx:ai:news:chunk:active` moved atomically to the second build.
- Live query on the second build: the quantum-computing question returned news 8 first with score 0.6684.
- Rollback: `FT.ALIASUPDATE` moved the Alias back to the initial build; the same query returned the same first result and score.
- Retention checks after rollback: v1 remained present, both v2 builds remained present, `ai:summary:*` stayed at 1 key, and `checkpoint*` stayed at 765 keys. No broad cache deletion was performed.

The first attempted build also exercised failure isolation: a binary-vector decode error during validation caused the exact candidate index and keys to be removed while the previous active build and unrelated Redis data remained untouched. Validation now uses `NOCONTENT` for its KNN health probe.

## Real tail-fact integration

`tests/integration/test_news_chunk_retrieval.py` creates uniquely prefixed temporary Redis Stack indexes, embeds the labeled long article through the real TEI service, and queries Redis HNSW. The tail fact after token 512 was retrieved from news 101, entered the token-bounded QA model context, and appeared in the client citation. The test passed and removed its temporary Alias, index, and keys; production indexes were not modified.

Run it explicitly with isolated-service URLs:

```powershell
$env:AI_RETRIEVAL_TEST_REDIS_URL = 'redis://127.0.0.1:6380/0'
$env:AI_RETRIEVAL_TEST_EMBEDDING_URL = 'http://127.0.0.1:8081'
uv run python -m pytest tests/integration/test_news_chunk_retrieval.py -q -rs
```
