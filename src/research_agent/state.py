"""State carried through the research graph."""

from typing import Annotated, TypedDict
import operator


class Page(TypedDict):
    """One fetched page: where it came from and what it said."""

    url: str
    text: str


class SearchLogEntry(TypedDict):
    query: str
    status: str  # "ok", "empty" or "timeout"
    result_count: int


class ResearchState(TypedDict):
    company_name: str
    website_url: str
    queries: list[dict]  # each: {"query": str, "params": dict} passed to the search client
    pages: Annotated[list[Page], operator.add]
    search_log: Annotated[list[SearchLogEntry], operator.add]
    tool_calls: int
    timed_out: bool
    stop_reason: str
    record_path: str
