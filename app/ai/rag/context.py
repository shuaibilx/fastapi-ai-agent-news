"""Token-bounded, source-traceable context assembly for news RAG."""

from dataclasses import dataclass, replace
from typing import Protocol

from app.ai.rag.retrieval import RetrievedArticle, RetrievedPassage


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...


@dataclass(frozen=True)
class RetrievalContext:
    context: str
    articles: tuple[RetrievedArticle, ...]
    token_count: int


class RetrievalContextBuilder:
    """Add only whole de-overlapped passages that fit the configured budget."""

    def __init__(self, *, token_counter: TokenCounter, max_tokens: int):
        if max_tokens < 1:
            raise ValueError("max_tokens 必须大于 0")
        self._tokens = token_counter
        self._max_tokens = max_tokens

    def build(self, articles: list[RetrievedArticle]) -> RetrievalContext:
        sections: list[str] = []
        selected_articles: list[RetrievedArticle] = []
        for article in articles:
            selected_passages: list[RetrievedPassage] = []
            covered_end = -1
            passages = article.passages or self._legacy_passages(article)
            for passage in passages:
                candidate = self._remove_covered_prefix(passage, covered_end)
                if candidate is None:
                    continue
                rendered = self._render(article, candidate)
                candidate_context = "\n\n".join([*sections, rendered])
                if self._tokens.count(candidate_context) > self._max_tokens:
                    continue
                sections.append(rendered)
                selected_passages.append(candidate)
                covered_end = max(covered_end, candidate.end_index)
            if selected_passages:
                selected_articles.append(replace(
                    article,
                    passages=tuple(selected_passages),
                ))
        context = "\n\n".join(sections)
        return RetrievalContext(
            context=context,
            articles=tuple(selected_articles),
            token_count=self._tokens.count(context),
        )

    @staticmethod
    def _legacy_passages(article: RetrievedArticle) -> tuple[RetrievedPassage, ...]:
        text = article.excerpt or article.content or article.description or ""
        if not text:
            return ()
        return (RetrievedPassage(
            chunk_id=f"legacy:{article.id}",
            chunk_index=0,
            start_index=0,
            end_index=len(text),
            text=text,
            score=0.0,
        ),)

    @staticmethod
    def _remove_covered_prefix(
        passage: RetrievedPassage,
        covered_end: int,
    ) -> RetrievedPassage | None:
        if covered_end <= passage.start_index:
            return passage
        overlap = min(len(passage.text), covered_end - passage.start_index)
        text = passage.text[overlap:]
        if not text:
            return None
        return replace(
            passage,
            start_index=passage.start_index + overlap,
            text=text,
        )

    @staticmethod
    def _render(article: RetrievedArticle, passage: RetrievedPassage) -> str:
        return (
            f"[{article.id}|{passage.chunk_id}|{passage.start_index}-{passage.end_index}] "
            f"{article.title}\n{passage.text}"
        )
