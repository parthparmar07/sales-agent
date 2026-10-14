import json
from typing import get_type_hints

import pytest
from tavily.errors import TimeoutError as TavilyTimeoutError

from research_agent.graph import (
    TOOL_CALL_BUDGET,
    build_graph,
    initial_state,
    make_search_node,
    route_after_search,
)
from research_agent.state import Page, ResearchState


class FakeSearch:
    """Stands in for Tavily. `script` maps call number (1-based) to a response or an exception."""

    def __init__(self, script=None):
        self.script = script or {}
        self.calls = 0

    def __call__(self, query, **params):
        self.calls += 1
        outcome = self.script.get(self.calls)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is not None:
            return outcome
        return {"results": [{"url": f"https://example.com/p{self.calls}", "raw_content": f"text {self.calls}"}]}


def queries(n):
    return [{"query": f"q{i}", "params": {}} for i in range(n)]


def run(search, n_queries, tmp_path, company="Allbirds"):
    graph = build_graph(search, runs_dir=tmp_path)
    return graph.invoke(initial_state(company, "https://www.allbirds.com", queries(n_queries)))


# --- state fields ---

def test_page_holds_url_and_text():
    assert get_type_hints(Page) == {"url": str, "text": str}


def test_timeout_field_is_bool():
    assert get_type_hints(ResearchState)["timed_out"] is bool


def test_pages_in_final_state_have_url_and_text(tmp_path):
    final = run(FakeSearch(), 2, tmp_path)
    assert final["pages"] == [
        {"url": "https://example.com/p1", "text": "text 1"},
        {"url": "https://example.com/p2", "text": "text 2"},
    ]


# --- counter is incremented inside the search node ---

def test_search_node_increments_counter_itself():
    node = make_search_node(FakeSearch())
    update = node(initial_state("Allbirds", "https://www.allbirds.com", queries(3)) | {"tool_calls": 2})
    assert update["tool_calls"] == 3


def test_counter_equals_real_search_calls(tmp_path):
    search = FakeSearch()
    final = run(search, 5, tmp_path)
    assert final["tool_calls"] == search.calls == 5


# --- routing: budget and timeout each trigger the exit on their own ---

def state_with(tool_calls, timed_out, n_queries=20):
    return initial_state("A", "https://a.com", queries(n_queries)) | {"tool_calls": tool_calls, "timed_out": timed_out}


def test_route_continues_under_budget_without_timeout():
    assert route_after_search(state_with(3, False)) == "search"


def test_route_exits_at_budget_alone():
    assert route_after_search(state_with(TOOL_CALL_BUDGET, False)) == "finish"


def test_route_exits_on_timeout_alone():
    assert route_after_search(state_with(1, True)) == "finish"


def test_graph_stops_at_budget(tmp_path):
    search = FakeSearch()
    final = run(search, 20, tmp_path)
    assert search.calls == final["tool_calls"] == TOOL_CALL_BUDGET
    assert final["stop_reason"] == "budget"


# --- empty results and timeouts ---

@pytest.mark.parametrize("error", [TimeoutError(), TavilyTimeoutError(20)], ids=["builtin", "tavily"])
def test_timeout_sets_flag_and_exits(tmp_path, error):
    search = FakeSearch({2: error})
    final = run(search, 20, tmp_path)
    assert final["timed_out"] is True
    assert search.calls == final["tool_calls"] == 2
    assert final["stop_reason"] == "timeout"
    assert final["search_log"][-1]["status"] == "timeout"


def test_empty_results_add_no_pages_and_continue(tmp_path):
    search = FakeSearch({1: {"results": []}})
    final = run(search, 3, tmp_path)
    assert final["timed_out"] is False
    assert search.calls == 3
    assert [p["url"] for p in final["pages"]] == ["https://example.com/p2", "https://example.com/p3"]
    assert final["search_log"][0] == {"query": "q0", "status": "empty", "result_count": 0}


# --- run records ---

def test_record_has_company_and_urls(tmp_path):
    final = run(FakeSearch(), 2, tmp_path)
    record = json.loads(open(final["record_path"], encoding="utf-8").read())
    assert record["company_name"] == "Allbirds"
    assert record["website_url"] == "https://www.allbirds.com"
    assert record["fetched_urls"] == ["https://example.com/p1", "https://example.com/p2"]
    assert record["tool_calls"] == 2


def test_each_run_writes_its_own_record(tmp_path):
    first = run(FakeSearch(), 2, tmp_path)
    first_content = open(first["record_path"], encoding="utf-8").read()
    second = run(FakeSearch(), 3, tmp_path, company="Gymshark")

    assert first["record_path"] != second["record_path"]
    assert len(list(tmp_path.glob("*.json"))) == 2
    assert open(first["record_path"], encoding="utf-8").read() == first_content
