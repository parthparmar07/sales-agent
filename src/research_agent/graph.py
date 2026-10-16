"""Research graph: planner -> search (looping) -> writer.

The search loop exits to the writer when the tool-call budget is spent, a search times out,
a search returns no usable pages, or the planned queries run out.
"""

import builtins
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from langgraph.graph import END, START, StateGraph

from research_agent.state import Page, ResearchState

TOOL_CALL_BUDGET = 8  # matches rule 6 of the briefing contract

try:
    from tavily.errors import TimeoutError as TavilyTimeoutError
except ImportError:  # tavily not installed; only the built-in timeout can occur
    TavilyTimeoutError = builtins.TimeoutError

TIMEOUT_ERRORS = (builtins.TimeoutError, TavilyTimeoutError)

SearchFn = Callable[..., dict]
PlanFn = Callable[[str, str], list[dict]]


def company_domain(website_url: str) -> str:
    host = urlparse(website_url).netloc.lower()
    return host.removeprefix("www.")


def default_queries(company_name: str, website_url: str) -> list[dict]:
    """One query per briefing need. Company-site queries are restricted to the company's domain."""
    on_site = {"include_domains": [company_domain(website_url)]}
    return [
        {"query": f"{company_name} what the company does", "params": on_site},
        {"query": f"{company_name} about founded headquarters", "params": on_site},
        {"query": f"{company_name} news announcements", "params": {"topic": "news", "days": 90}},
        {"query": f"{company_name} pricing plans products", "params": on_site},
        {"query": f"{company_name} customers partners", "params": on_site},
    ]


def stop_reason(state: ResearchState, budget: int = TOOL_CALL_BUDGET) -> str | None:
    """Why the search loop must stop now, or None to keep searching. Each condition alone is enough."""
    if state["timed_out"]:
        return "timeout"
    if state["search_log"] and state["search_log"][-1]["status"] == "empty":
        return "empty_results"
    if state["tool_calls"] >= budget:
        return "budget"
    if state["tool_calls"] >= len(state["queries"]):
        return "queries_exhausted"
    return None


def route_after_search(state: ResearchState, budget: int = TOOL_CALL_BUDGET) -> str:
    return "search" if stop_reason(state, budget) is None else "writer"


def make_planner_node(plan_fn: PlanFn):
    def planner(state: ResearchState) -> dict:
        return {"queries": plan_fn(state["company_name"], state["website_url"])}

    return planner


def make_search_node(search_fn: SearchFn):
    def search(state: ResearchState) -> dict:
        planned = state["queries"][state["tool_calls"]]
        # Count the call before making it: a call that times out still spent budget.
        tool_calls = state["tool_calls"] + 1
        try:
            response = search_fn(planned["query"], **planned.get("params", {}))
        except TIMEOUT_ERRORS:
            return {
                "tool_calls": tool_calls,
                "timed_out": True,
                "search_log": [{"query": planned["query"], "status": "timeout", "result_count": 0}],
            }

        results = (response or {}).get("results") or []
        # A page needs both a URL and text; a result missing either is dropped, never stored half-filled.
        usable = [
            {"url": r["url"], "text": r.get("raw_content") or r.get("content")}
            for r in results
            if r.get("url") and (r.get("raw_content") or r.get("content"))
        ]
        seen = {page["url"] for page in state["pages"]}
        new_pages: list[Page] = []
        for page in usable:
            if page["url"] not in seen:
                seen.add(page["url"])
                new_pages.append(page)

        return {
            "tool_calls": tool_calls,
            "pages": new_pages,
            "search_log": [
                {"query": planned["query"], "status": "ok" if usable else "empty", "result_count": len(usable)}
            ],
        }

    return search


def writer(state: ResearchState) -> dict:
    # shortcut: writes a contract-shaped skeleton with no facts, replace with the LLM writer in the next stage
    gap = "Not found in sources"
    briefing = (
        f"## What the company does\n{gap}\n\n"
        f"## What changed in the last 90 days\n{gap}\n\n"
        f"## Three talking points\n{gap}\n\n"
        f"Tool calls used: {state['tool_calls']}"
    )
    return {"briefing": briefing}


def build_graph(search_fn: SearchFn, plan_fn: PlanFn = default_queries, budget: int = TOOL_CALL_BUDGET):
    route = {"search": "search", "writer": "writer"}
    graph = StateGraph(ResearchState)
    graph.add_node("planner", make_planner_node(plan_fn))
    graph.add_node("search", make_search_node(search_fn))
    graph.add_node("writer", writer)
    graph.add_edge(START, "planner")
    graph.add_conditional_edges("planner", lambda s: route_after_search(s, budget), route)
    graph.add_conditional_edges("search", lambda s: route_after_search(s, budget), route)
    graph.add_edge("writer", END)
    return graph.compile()


def initial_state(company_name: str, website_url: str) -> ResearchState:
    return {
        "company_name": company_name,
        "website_url": website_url,
        "queries": [],
        "pages": [],
        "search_log": [],
        "tool_calls": 0,
        "timed_out": False,
        "briefing": "",
    }


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def write_run_record(
    state: ResearchState,
    runs_dir: Path | str = "runs",
    budget: int = TOOL_CALL_BUDGET,
    trace_url: str | None = None,
) -> Path:
    """Write one finished run to its own new file. Mode "x" refuses to overwrite or append to an existing record."""
    runs_dir = Path(runs_dir)
    runs_dir.mkdir(parents=True, exist_ok=True)
    written_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"{written_at}_{_slug(state['company_name'])}_{uuid.uuid4().hex[:8]}"
    path = runs_dir / f"{run_id}.json"
    record = {
        "run_id": run_id,
        "company_name": state["company_name"],
        "website_url": state["website_url"],
        "tool_calls": state["tool_calls"],
        "budget": budget,
        "timed_out": state["timed_out"],
        "stop_reason": stop_reason(state, budget),
        "fetched_urls": [page["url"] for page in state["pages"]],
        "searches": state["search_log"],
        "briefing": state["briefing"],
        "trace_url": trace_url,
    }
    with path.open("x", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    return path


def tavily_search_fn(api_key: str, timeout: float = 20) -> SearchFn:
    from tavily import TavilyClient

    client = TavilyClient(api_key=api_key)

    def search(query: str, **params) -> dict:
        return client.search(query, max_results=3, include_raw_content="text", timeout=timeout, **params)

    return search
