"""Shared query-parameter types and pagination constants.

API gateways -- RapidAPI's playground among them -- send every *unset* optional
parameter as an empty string rather than omitting it, producing URLs like:

    /recalls?agency=&category=&since=&until=&page=&per_page=

Pydantic rejects "" for date and int parameters, so the whole request 422s even
though the caller supplied no filters at all. These types normalize a blank (or
whitespace-only) value to None *before* validation, so a blank parameter means
"filter not applied".

This only strips blanks. A non-empty but invalid value (`since=banana`,
`per_page=101`) still fails validation and still returns a clear 422 -- the
caller made a real mistake and should hear about it.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from pydantic import BeforeValidator, Field

MAX_PER_PAGE = 100
DEFAULT_PER_PAGE = 25
DEFAULT_PAGE = 1


def blank_to_none(value: Any) -> Any:
    """Map "" and whitespace-only strings to None, leave everything else alone."""
    if isinstance(value, str) and not value.strip():
        return None
    return value


# Runs before type coercion, so "" never reaches the date/int parser.
Blankable = BeforeValidator(blank_to_none)

OptionalText = Annotated[str | None, Blankable]
OptionalDate = Annotated[date | None, Blankable]

# Numeric bounds must sit on the `int` member of the union, not on the union
# itself. Declaring the constraint at the outer level (e.g. Query(ge=1) over
# `int | None`) makes Pydantic try to apply `ge` to None and raise
# "Unable to apply constraint 'ge' to supplied value None" -- a 500, not a 422.
PageNumber = Annotated[Annotated[int, Field(ge=1)] | None, Blankable]
PerPageNumber = Annotated[Annotated[int, Field(ge=1, le=MAX_PER_PAGE)] | None, Blankable]
