from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

T = TypeVar("T")
K = TypeVar("K")


@dataclass(slots=True, frozen=True)
class BatchError(Generic[K]):
    key: K
    error: Exception


@dataclass(slots=True)
class BatchResult(Generic[K, T]):
    successful: list[T] = field(default_factory=list)
    failed: list[BatchError[K]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed

    def raise_for_errors(self) -> None:
        if self.failed:
            first = self.failed[0]
            raise first.error


@dataclass(slots=True, frozen=True)
class StreamItemResult(Generic[K, T]):
    """Runtime result for one item in a concurrent stream."""

    key: K
    value: T | None = None
    error: Exception | None = None

    @property
    def ok(self) -> bool:
        return self.error is None
