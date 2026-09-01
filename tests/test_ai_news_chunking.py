from pathlib import Path

import pytest


TOKENIZER_PATH = Path("app/embedding/bge-large-zh-v1.5/tokenizer.json")


def test_normalization_and_chunk_identity_are_deterministic():
    """Unstable cleanup or IDs would create duplicate vectors on identical rebuilds."""
    from app.ai.rag.chunking import BgeTokenCounter, NewsChunker, normalize_news_text

    raw = "<p>第一段&nbsp;新闻。</p>\r\n\r\n<p>第二段   新闻。</p>"
    normalized = normalize_news_text(raw)
    chunker = NewsChunker(
        token_counter=BgeTokenCounter(TOKENIZER_PATH),
        chunk_size_tokens=320,
        chunk_overlap_tokens=48,
        embedding_input_max_tokens=480,
    )

    first = chunker.split(
        news_id=7,
        title="测试新闻",
        description="测试简介",
        content=raw,
    )
    second = chunker.split(
        news_id=7,
        title="测试新闻",
        description="测试简介",
        content=raw,
    )

    assert normalized == "第一段 新闻。\n\n第二段 新闻。"
    assert first == second
    assert first[0].chunk_id.startswith("7:0:")
    assert first[0].content_hash == second[0].content_hash
    assert first[0].chunk_text == normalized


def test_short_news_uses_one_chunk_and_separates_embedding_text_from_excerpt():
    """Short articles must not produce duplicate vectors or polluted citation text."""
    from app.ai.rag.chunking import BgeTokenCounter, NewsChunker

    counter = BgeTokenCounter(TOKENIZER_PATH)
    chunker = NewsChunker(
        token_counter=counter,
        chunk_size_tokens=320,
        chunk_overlap_tokens=48,
        embedding_input_max_tokens=480,
    )

    chunks = chunker.split(
        news_id=8,
        title="人工智能产业进展",
        description="产业规模持续增长",
        content="企业正在扩大人工智能基础设施投入。",
    )

    assert len(chunks) == 1
    assert chunks[0].chunk_text == "企业正在扩大人工智能基础设施投入。"
    assert "标题：人工智能产业进展" in chunks[0].embedding_text
    assert "简介：产业规模持续增长" in chunks[0].embedding_text
    assert counter.count(chunks[0].embedding_text) <= 480


def test_long_chinese_news_preserves_tail_facts_with_bounded_overlap():
    """A fact beyond the old 512-token window must remain independently retrievable."""
    from app.ai.rag.chunking import BgeTokenCounter, NewsChunker

    counter = BgeTokenCounter(TOKENIZER_PATH)
    prefix = "。".join(f"这是第{i}段关于产业发展的背景信息" for i in range(90)) + "。"
    tail_fact = "关键事实：火星基地计划将在二零三零年启动。"
    content = prefix + tail_fact
    chunker = NewsChunker(
        token_counter=counter,
        chunk_size_tokens=96,
        chunk_overlap_tokens=16,
        embedding_input_max_tokens=160,
    )

    chunks = chunker.split(
        news_id=9,
        title="长期规划新闻",
        description="背景介绍",
        content=content,
    )

    assert len(chunks) > 1
    assert any(tail_fact in chunk.chunk_text for chunk in chunks)
    assert all(counter.count(chunk.embedding_text) <= 160 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.start_index < chunk.end_index for chunk in chunks)


def test_chunker_rejects_invalid_budget_relationships():
    """An overlap equal to the chunk or a chunk above the input cap can loop or truncate."""
    from app.ai.rag.chunking import BgeTokenCounter, NewsChunker

    counter = BgeTokenCounter(TOKENIZER_PATH)
    with pytest.raises(ValueError):
        NewsChunker(
            token_counter=counter,
            chunk_size_tokens=100,
            chunk_overlap_tokens=100,
            embedding_input_max_tokens=160,
        )
    with pytest.raises(ValueError):
        NewsChunker(
            token_counter=counter,
            chunk_size_tokens=161,
            chunk_overlap_tokens=20,
            embedding_input_max_tokens=160,
        )
