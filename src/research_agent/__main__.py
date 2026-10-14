"""Run the research graph live against Tavily.

python -m research_agent --company Allbirds --url https://www.allbirds.com
python -m research_agent --csv data/test_companies.csv
"""

import argparse
import csv
import os
import sys

from dotenv import load_dotenv

from research_agent.graph import build_graph, initial_state, tavily_search_fn


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

    graph = build_graph(tavily_search_fn(api_key), runs_dir=args.runs_dir)
    for name, url in companies:
        final = graph.invoke(initial_state(name, url))
        print(f"{name}: {final['tool_calls']} tool calls, {len(final['pages'])} pages, "
              f"stopped on {final['stop_reason']} -> {final['record_path']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
