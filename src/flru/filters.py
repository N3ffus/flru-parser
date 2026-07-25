from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any


class ProjectType(StrEnum):
    ORDER = "1"
    VACANCY = "2"
    CONTEST = "3"


@dataclass(slots=True, frozen=True)
class ProjectFilters:
    query: str | None = None
    category: str | None = None
    budget_from: Decimal | int | None = None
    budget_to: Decimal | int | None = None
    project_types: frozenset[ProjectType] = field(default_factory=frozenset)
    only_with_budget: bool | None = None
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_params(self) -> dict[str, Any]:
        params: dict[str, Any] = dict(self.extra)
        if self.query:
            params["search"] = self.query
        if self.budget_from is not None:
            params["budget_from"] = str(self.budget_from)
        if self.budget_to is not None:
            params["budget_to"] = str(self.budget_to)
        if self.project_types:
            params["kind"] = [item.value for item in sorted(self.project_types)]
        if self.only_with_budget is not None:
            params["with_budget"] = int(self.only_with_budget)
        return params
