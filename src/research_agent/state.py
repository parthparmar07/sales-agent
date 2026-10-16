"""State carried through the research graph."""

from typing import Annotated, TypedDict
import operator


class Page(TypedDict):
    """One fetched page: where it came from and what it said. Both are always non-empty."""

    url: str
    text: str


class SearchLogEntry(TypedDict):
    query: str
    status: str  # "ok", "empty" or "timeout"
    result_count: int


class ResearchState(TypedDict):
    company_name: str
    website_url: str
    queries: list[dict]  # set by the planner; each {"query": str, "params": dict} for the search client
    pages: Annotated[list[Page], operator.add]
    search_log: Annotated[list[SearchLogEntry], operator.add]
    tool_calls: int
    timed_out: bool
    briefing: str  # set by the writer
