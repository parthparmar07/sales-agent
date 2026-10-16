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
    write_run_record,
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


def run(search, n_queries, company="Allbirds"):
    graph = build_graph(search, plan_fn=lambda name, url: queries(n_queries))
    return graph.invoke(initial_state(company, "https://www.allbirds.com"))


def state_with(tool_calls, timed_out, n_queries=20, log=()):
    return initial_state("A", "https://a.com") | {
        "queries": queries(n_queries),
        "tool_calls": tool_calls,
        "timed_out": timed_out,
        "search_log": list(log),
    }


# --- state fields ---

def test_page_holds_url_and_text():
    assert get_type_hints(Page) == {"url": str, "text": str}


def test_timeout_field_is_bool():
    assert get_type_hints(ResearchState)["timed_out"] is bool


def test_state_has_briefing_string():
    assert get_type_hints(ResearchState)["briefing"] is str


def test_pages_in_final_state_have_url_and_text():
    final = run(FakeSearch(), 2)
    assert final["pages"] == [
        {"url": "https://example.com/p1", "text": "text 1"},
        {"url": "https://example.com/p2", "text": "text 2"},
    ]


def test_result_without_text_is_not_stored():
    search = FakeSearch({1: {"results": [{"url": "https://example.com/blank", "content": ""},
                                         {"url": "https://example.com/full", "content": "full text"}]}})
    final = run(search, 1)
    assert final["pages"] == [{"url": "https://example.com/full", "text": "full text"}]


# --- planner ---

def test_planner_sets_queries():
    final = run(FakeSearch(), 3)
    assert [q["query"] for q in final["queries"]] == ["q0", "q1", "q2"]


# --- counter is incremented inside the search node ---

def test_search_node_increments_counter_itself():
    node = make_search_node(FakeSearch())
    assert node(state_with(2, False))["tool_calls"] == 3


def test_counter_equals_real_search_calls():
    search = FakeSearch()
    final = run(search, 5)
    assert final["tool_calls"] == search.calls == 5


# --- routing: budget, timeout and empty results each send the run to the writer on their own ---

def test_route_continues_under_budget_without_timeout():
    assert route_after_search(state_with(3, False)) == "search"


def test_route_exits_at_budget_alone():
    assert route_after_search(state_with(TOOL_CALL_BUDGET, False)) == "writer"


def test_route_exits_on_timeout_alone():
    assert route_after_search(state_with(1, True)) == "writer"


def test_route_exits_on_empty_results_alone():
    log = [{"query": "q0", "status": "empty", "result_count": 0}]
    assert route_after_search(state_with(1, False, log=log)) == "writer"


def test_graph_stops_at_budget():
    search = FakeSearch()
    final = run(search, 20)
    assert search.calls == final["tool_calls"] == TOOL_CALL_BUDGET


# --- empty results and timeouts both stop the search and reach the writer ---

@pytest.mark.parametrize("error", [TimeoutError(), TavilyTimeoutError(20)], ids=["builtin", "tavily"])
def test_timeout_sets_flag_and_goes_to_writer(error):
    search = FakeSearch({2: error})
    final = run(search, 20)
    assert final["timed_out"] is True
    assert search.calls == final["tool_calls"] == 2
    assert final["search_log"][-1]["status"] == "timeout"
    assert final["briefing"].endswith("Tool calls used: 2")


def test_empty_results_stop_search_and_go_to_writer():
    search = FakeSearch({2: {"results": []}})
    final = run(search, 20)
    assert search.calls == final["tool_calls"] == 2
    assert final["timed_out"] is False
    assert [p["url"] for p in final["pages"]] == ["https://example.com/p1"]
    assert final["search_log"][-1] == {"query": "q1", "status": "empty", "result_count": 0}
    assert final["briefing"].endswith("Tool calls used: 2")


# --- run records ---

def test_record_has_company_urls_and_stop_reason(tmp_path):
    final = run(FakeSearch(), 2)
    record = json.loads(write_run_record(final, tmp_path).read_text(encoding="utf-8"))
    assert record["company_name"] == "Allbirds"
    assert record["website_url"] == "https://www.allbirds.com"
    assert record["fetched_urls"] == ["https://example.com/p1", "https://example.com/p2"]
    assert record["tool_calls"] == 2
    assert record["stop_reason"] == "queries_exhausted"
    assert record["briefing"] == final["briefing"]


def test_each_run_writes_its_own_record(tmp_path):
    first = write_run_record(run(FakeSearch(), 2), tmp_path)
    first_content = first.read_text(encoding="utf-8")
    second = write_run_record(run(FakeSearch(), 3, company="Gymshark"), tmp_path)

    assert first != second
    assert len(list(tmp_path.glob("*.json"))) == 2
    assert first.read_text(encoding="utf-8") == first_content
