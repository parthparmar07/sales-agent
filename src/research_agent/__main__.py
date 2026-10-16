"""Run the research graph live against Tavily, write a run record, and share the LangSmith trace.

python -m research_agent --company Allbirds --url https://www.allbirds.com
python -m research_agent --csv data/test_companies.csv
"""

import argparse
import csv
import os
import sys
import uuid

from dotenv import load_dotenv

from research_agent.graph import build_graph, initial_state, stop_reason, tavily_search_fn, write_run_record


def share_trace(run_id: uuid.UUID) -> str | None:
    """Return a public LangSmith link for this run, or None when tracing is off."""
    from langsmith.utils import tracing_is_enabled

    if not tracing_is_enabled():
        return None
    from langchain_core.tracers.langchain import wait_for_all_tracers
    from langsmith import Client

    wait_for_all_tracers()  # the run must be uploaded before it can be shared
    return Client().share_run(run_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company")
    parser.add_argument("--url")
    parser.add_argument("--csv", help="CSV with prospect_company_name and website_url columns")
    parser.add_argument("--runs-dir", default="runs")
    args = parser.parse_args()

    load_dotenv()
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        print("TAVILY_API_KEY is empty. Add it to .env first.", file=sys.stderr)
        return 1

    if args.csv:
        with open(args.csv, encoding="utf-8", newline="") as f:
            companies = [(r["prospect_company_name"], r["website_url"]) for r in csv.DictReader(f)]
    elif args.company and args.url:
        companies = [(args.company, args.url)]
    else:
        parser.error("pass --company and --url, or --csv")

    graph = build_graph(tavily_search_fn(api_key))
    for name, url in companies:
        run_id = uuid.uuid4()
        final = graph.invoke(initial_state(name, url), config={"run_id": run_id, "run_name": f"research: {name}"})
        trace_url = share_trace(run_id)
        path = write_run_record(final, args.runs_dir, trace_url=trace_url)
        print(f"{name} ({url}): {final['tool_calls']} tool calls, stopped on {stop_reason(final)}")
        for page in final["pages"]:
            print(f"  - {page['url']}")
        print(f"  record: {path.as_posix()}")
        print(f"  trace: {trace_url or 'tracing off (set LANGSMITH_TRACING=true and LANGSMITH_API_KEY)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
