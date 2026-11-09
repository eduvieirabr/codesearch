"""Snapshot pinning and explicit serialized response budgets."""

from __future__ import annotations

import base64
import copy
import json
import threading
from dataclasses import dataclass, field
from functools import wraps

from .indexer import CodeIndex
from .parser import SymbolInfo


def serialized_size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False))


def validate_budget(max_chars: int) -> None:
    if not 1024 <= max_chars <= 128_000:
        raise ValueError("max_chars must be between 1024 and 128000")


def bounded_response(
    payload: dict, items: list[dict], max_chars: int, key: str = "results"
) -> dict:
    """Budget all serialized JSON, preserving order and reporting omitted entries."""
    validate_budget(max_chars)
    result = {
        **payload,
        key: [],
        "budget": {"limit_chars": max_chars, "used_chars": 0},
        "truncated": False,
        "omitted_count": 0,
    }
    # Reserve the longest possible metadata before admitting payload entries.
    result["budget"]["used_chars"] = max_chars
    prior_omitted = payload.get("omitted_count", 0)
    result["omitted_count"] = len(items) + prior_omitted
    result["truncated"] = False  # JSON false is one character longer than true.
    if serialized_size(result) > max_chars:
        raise ValueError("Budget too small for request metadata; use a larger max_chars")
    for original in items:
        item = copy.deepcopy(original)
        result[key].append(item)
        if serialized_size(result) > max_chars:
            source = item.get("source")
            cursor = item.get("source_cursor")
            if source and cursor:
                state = decode_cursor(cursor)
                start = state["p"]
                item["source_truncated"] = True
                low, high = 0, len(source)
                while low < high:
                    size = (low + high + 1) // 2
                    item["source"] = source[:size]
                    item["next_cursor"] = encode_cursor({**state, "p": start + size})
                    if serialized_size(result) <= max_chars:
                        low = size
                    else:
                        high = size - 1
                item["source"] = source[:low]
                item["next_cursor"] = encode_cursor({**state, "p": start + low})
                if low:
                    break
            result[key].pop()
            break
    result["omitted_count"] = prior_omitted + len(items) - len(result[key])
    result["truncated"] = bool(
        payload.get("truncated")
        or result["omitted_count"]
        or any(item.get("source_truncated") for item in result[key])
    )
    for _ in range(4):
        result["budget"]["used_chars"] = serialized_size(result)
    return result


def encode_cursor(data: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()


def decode_cursor(value: str) -> dict:
    if len(value) > 2000:
        raise ValueError("Invalid continuation cursor")
    try:
        result = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid continuation cursor") from exc
    if not isinstance(result, dict):
        raise ValueError("Invalid continuation cursor")
    return result


@dataclass
class Snapshot:
    generation: int
    report: dict
    files: tuple[dict, ...]
    changes: dict = field(default_factory=dict)
    by_path: dict = field(init=False)
    _cache: dict = field(default_factory=dict)
    _lock: object = field(default_factory=threading.RLock)

    def __post_init__(self):
        self.by_path = {row["path"]: row for row in self.files}

    @property
    def symbols(self) -> list[SymbolInfo]:
        with self._lock:
            if "symbols" not in self._cache:
                self._cache["symbols"] = [
                    SymbolInfo(**symbol) for row in self.files for symbol in row["symbols"]
                ]
            return self._cache["symbols"]

    @property
    def index(self):
        with self._lock:
            if "index" not in self._cache:
                self._cache["index"] = CodeIndex(self.symbols)
            return self._cache["index"]

    @property
    def relations(self):
        with self._lock:
            if "relations" not in self._cache:
                from .relationships import DependencyAnalysis

                self._cache["relations"] = DependencyAnalysis(list(self.files))
            return self._cache["relations"]


def pinned_tool(function):
    """Nested calls reuse one request-local snapshot without mutable service-wide fields."""

    @wraps(function)
    def wrapped(self, *args, **kwargs):
        current = self._request.get()
        if current is not None:
            return function(self, *args, **kwargs)
        request = {"snapshot": None}
        token = self._request.set(request)
        try:
            result = function(self, *args, **kwargs)
            if isinstance(result, dict) and request["snapshot"] is not None:
                result.setdefault("_meta", self._metadata(request["snapshot"]))
            return result
        finally:
            self._request.reset(token)

    return wrapped
