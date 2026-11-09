"""Deterministic lexical ranking with exact-name and scope-aware retrieval."""

from __future__ import annotations

import fnmatch
import re

from rank_bm25 import BM25Okapi

from .parser import SymbolInfo

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_WORD = re.compile(r"[\W_]+", re.UNICODE)


def _tokenize(text: str) -> set[str]:
    out: set[str] = set()
    for raw in text.split():
        out.add(raw.casefold())
        out.update(
            piece.casefold() for piece in _NON_WORD.split(_CAMEL_BOUNDARY.sub(" ", raw)) if piece
        )
    return out


def path_matches(path: str, pattern: str | None) -> bool:
    if not pattern:
        return True
    path, pattern = path.casefold(), pattern.replace("\\", "/").casefold()
    return fnmatch.fnmatchcase(path, pattern) or (
        pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:])
    )


def match_type(symbol: SymbolInfo, query: str) -> str:
    query = query.strip()
    names = {symbol.name, getattr(symbol, "qualified_name", "")}
    if query and query in names:
        return "exact"
    if query and query.casefold() in {name.casefold() for name in names}:
        return "exact_casefold"
    return "lexical" if query else "filter"


class CodeIndex:
    def __init__(self, symbols: list[SymbolInfo]):
        self._symbols = symbols
        self._corpus_tokens = [
            _tokenize(f"{s.name} {getattr(s, 'qualified_name', '')} {s.summary}") for s in symbols
        ]
        corpus = [sorted(tokens) or [""] for tokens in self._corpus_tokens]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def search(
        self,
        query: str,
        limit: int = 10,
        kind: str | None = "function",
        language: str | None = None,
        file_pattern: str | None = None,
        decorator: str | None = None,
    ) -> list[SymbolInfo]:
        if limit < 1 or not self._symbols:
            return []
        query = query.strip()
        tokens = sorted(_tokenize(query))
        if not tokens and not any((language, file_pattern, decorator)):
            return []
        scores = self._bm25.get_scores(tokens) if tokens else [0.0] * len(self._symbols)
        candidates = []
        for symbol, doc_tokens, score in zip(self._symbols, self._corpus_tokens, scores):
            if kind is not None and symbol.kind != kind:
                continue
            if language and getattr(symbol, "language", "") != language:
                continue
            if not path_matches(symbol.file, file_pattern):
                continue
            if decorator and not any(
                fnmatch.fnmatchcase(value.lstrip("@").split("(")[0], decorator.lstrip("@"))
                for value in getattr(symbol, "decorators", ())
            ):
                continue
            category = match_type(symbol, query)
            tier = {"exact": 0, "exact_casefold": 1}.get(category, 2)
            if tokens and tier == 2 and not set(tokens).intersection(doc_tokens):
                continue
            candidates.append(
                (tier, -float(score), symbol.file, symbol.line, symbol.kind, symbol.name, symbol)
            )
        candidates.sort(key=lambda row: row[:-1])
        return [row[-1] for row in candidates[:limit]]
