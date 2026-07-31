from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


@dataclass(slots=True)
class NormalizedRecall:
    """One recall, in the shape the `recalls` table expects.

    Every adapter in fetcher/sources/ yields these and nothing else, so the
    upsert path never needs to know which agency a record came from.
    """

    agency: str
    source_id: str
    product: str | None = None
    brand: str | None = None
    category: str | None = None
    hazard: str | None = None
    classification: str | None = None
    recall_date: date | None = None
    published_at: datetime | None = None
    url: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.agency:
            raise ValueError("agency is required")
        if not self.source_id:
            # Half of the UNIQUE key. An empty value would collapse unrelated
            # recalls onto one row, so fail loudly at the adapter instead.
            raise ValueError(f"{self.agency}: source_id is required")
