"""Research graph: search until the tool-call budget is spent, a search times out, or queries run out."""

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


def route_after_search(state: ResearchState, budget: int = TOOL_CALL_BUDGET) -> str:
    """Exit when the budget is spent OR a search timed out OR no queries are left. Each alone is enough."""
    if state["timed_out"]:
        return "finish"
    if state["tool_calls"] >= budget:
        return "finish"
    if state["tool_calls"] >= len(state["queries"]):
        return "finish"
    return "search"


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
        seen = {page["url"] for page in state["pages"]}
        new_pages: list[Page] = []
        for result in results:
            url = result.get("url")
            text = result.get("raw_content") or result.get("content") or ""
            if url and url not in seen:
                seen.add(url)
                new_pages.append({"url": url, "text": text})

        return {
            "tool_calls": tool_calls,
            "pages": new_pages,
            "search_log": [
                {"query": planned["query"], "status": "ok" if results else "empty", "result_count": len(results)}
            ],
        }

    return search


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def write_run_record(state: ResearchState, runs_dir: Path, budget: int, started_at: str) -> Path:
    """Write this run to its own new file. Mode "x" refuses to overwrite or append to an existing record."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    run_id = f"{started_at.replace(':', '').replace('-', '')}_{_slug(state['company_name'])}_{uuid.uuid4().hex[:8]}"
    path = runs_dir / f"{run_id}.json"
    record = {
        "run_id": run_id,
        "company_name": state["company_name"],
        "website_url": state["website_url"],
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool_calls": state["tool_calls"],
        "budget": budget,
        "timed_out": state["timed_out"],
        "stop_reason": state["stop_reason"],
        "fetched_urls": [page["url"] for page in state["pages"]],
        "searches": state["search_log"],
    }
    with path.open("x", encoding="utf-8") as f:
        json.dump(record, f, indent=2)
    return path


def build_graph(search_fn: SearchFn, runs_dir: Path | str = "runs", budget: int = TOOL_CALL_BUDGET):
    runs_dir = Path(runs_dir)
    started = {}

    def start(state: ResearchState) -> dict:
        started["at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return {}

    def finish(state: ResearchState) -> dict:
        if state["timed_out"]:
            reason = "timeout"
        elif state["tool_calls"] >= budget:
            reason = "budget"
        else:
            reason = "queries_exhausted"
        state = {**state, "stop_reason": reason}
        path = write_run_record(state, runs_dir, budget, started["at"])
        return {"stop_reason": reason, "record_path": str(path)}

    graph = StateGraph(ResearchState)
    graph.add_node("start", start)
    graph.add_node("search", make_search_node(search_fn))
    graph.add_node("finish", finish)
    graph.add_edge(START, "start")
    graph.add_conditional_edges("start", lambda s: route_after_search(s, budget), {"search": "search", "finish": "finish"})
    graph.add_conditional_edges("search", lambda s: route_after_search(s, budget), {"search": "search", "finish": "finish"})
    graph.add_edge("finish", END)
    return graph.compile()


def initial_state(company_name: str, website_url: str, queries: list[dict] | None = None) -> ResearchState:
    return {
        "company_name": company_name,
        "website_url": website_url,
        "queries": queries if queries is not None else default_queries(company_name, website_url),
        "pages": [],
        "search_log": [],
        "tool_calls": 0,
        "timed_out": False,
        "stop_reason": "",
        "record_path": "",
    }


def tavily_search_fn(api_key: str, timeout: float = 20) -> SearchFn:
    from tavily import TavilyClient

    client = TavilyClient(api_key=api_key)

    def search(query: str, **params) -> dict:
        return client.search(query, max_results=3, include_raw_content="text", timeout=timeout, **params)

    return search
