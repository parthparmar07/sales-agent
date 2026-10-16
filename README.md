# Sales Call Briefing Validator

A sales call briefing is a short Markdown document a rep reads before a call.
This repo defines exactly what a valid briefing looks like (the contract below)
and ships a validator that checks briefings against it.

## Setup

```
pip install -r requirements.txt
pip install -e .
cp .env.example .env   # then fill in your keys
pytest -v
```

`.env` holds `OPENROUTER_API_KEY`, `TAVILY_API_KEY` and `LANGSMITH_API_KEY`.
It is git-ignored; only `.env.example` (empty values) is committed.

## Using the validator

```python
from briefing_validator.validator import validate

result = validate(briefing_markdown, fetched_urls)
if not result.valid:
    for reason in result.errors:
        print(reason)
```

**Inputs**

| Argument | Type | What it is |
|---|---|---|
| `briefing_markdown` | `str` | The full briefing as Markdown, from the first `##` heading through the `Tool calls used: N` line. |
| `fetched_urls` | `list[str]` | Every URL the writer actually fetched. Citations are matched against this list exactly (scheme, `www.`, trailing slash all count). |

**Return value:** a `Result` dataclass with two fields:

- `valid: bool`. This is `True` only if no rule was broken.
- `errors: list[str]`. Each entry is a human-readable reason, one per rule broken. It is empty when `valid` is `True`. The validator checks every rule and does not stop at the first failure, so one briefing can have several errors.

Possible error messages, by contract rule:

| Rule | Message starts with |
|---|---|
| 1 Sections | `headings must be exactly ...`, `section '<name>' is empty`, `content found before the first section heading` |
| 2 Talking points | `talking points must be numbered 1, 2, 3, got [...]` |
| 3 Sourcing | `sentence has no source URL: '<sentence>'`, `cited URL was not fetched: <url>` |
| 4 Gaps | `gap line must be exactly 'Not found in sources': '<line>'` |
| 5 Closing line | `last line must be 'Tool calls used: N'` |
| 6 Budget | `used N tool calls, budget is 8` |

The validator never raises on a malformed briefing. All problems come back in `errors`. A writer node can send `errors` back to the model as revision feedback.

To check a whole file of briefings (a JSON list of objects with `sample_id`, `briefing_markdown`, `fetched_urls` and optionally `expected_valid`), run:

```
python -m briefing_validator tests/data/briefings.json
```

This prints each verdict with its reasons. The exit code is 1 if any verdict differs from `expected_valid`.

## Research agent

`src/research_agent/` is a LangGraph graph that gathers source pages for a briefing using Tavily search.

```
START -> planner -> search <-> search ... -> writer -> END
```

- **planner** sets `queries` (one per briefing need; company-site queries are limited to the company's domain).
- **search** runs one planned query per visit and loops until a stop condition is met.
- **writer** owns `briefing`. It is a stub for now: it writes the contract's three headings with `Not found in sources` and the `Tool calls used: N` line. The LLM writer replaces it next stage.

**State** (`ResearchState` in [state.py](src/research_agent/state.py)):

| Field | Type | Meaning |
|---|---|---|
| `company_name`, `website_url` | `str` | The prospect being researched. |
| `queries` | `list[dict]` | Planned searches from the planner, each `{"query", "params"}`. |
| `pages` | `list[Page]` | Every fetched page as `{"url": str, "text": str}`. Both are always non-empty. |
| `search_log` | `list[dict]` | One entry per search: `query`, `status` (`ok` / `empty` / `timeout`), `result_count`. |
| `tool_calls` | `int` | Searches made so far. |
| `timed_out` | `bool` | `True` once any search times out. |
| `briefing` | `str` | The briefing Markdown, set by the writer. |

The stop reason, trace link and record path are not in state. They only go into the run record.

**Rules the graph follows:**

- **Counting:** the `search` node increments `tool_calls` itself, before it calls Tavily. A search that times out still counts against the budget.
- **Routing:** after every search, `route_after_search` goes to the writer if any one of these is true: `timed_out`, the last search was `empty`, `tool_calls` reached the budget of 8, or no planned queries are left.
- **Empty results:** a search with no usable pages is logged as `empty`, and the graph stops searching and goes to the writer, the same as a timeout. A result with a URL but no text is dropped rather than stored as a half-filled page.
- **Timeouts:** both Python's `TimeoutError` and Tavily's `tavily.errors.TimeoutError` are caught. The node sets `timed_out = True` in state, logs the search as `timeout`, and the graph goes to the writer.
- **Run records:** `write_run_record` writes each finished run to its own new file, `runs/<timestamp>_<company>_<id>.json`. The file is opened with mode `x`, so an existing record is never overwritten or appended to. The record holds the company, website, fetched URLs, tool calls, timeout flag, stop reason, search log, briefing and trace link.

**Tracing:** LangSmith records a LangGraph run only when `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` are both set (`LANGSMITH_PROJECT` picks the project). With tracing on, the CLI waits for the trace to upload, makes it public with `Client.share_run`, prints the link and saves it in the run record.

Run it live (requires `TAVILY_API_KEY` in `.env`):

```
python -m research_agent --company Allbirds --url https://www.allbirds.com
python -m research_agent --csv data/test_companies.csv
```

For each company it prints the tool-call count, the stop reason, every fetched URL, the record path and the trace link.

`data/test_companies.csv` holds the 10 HubSpot first-call test companies (TC-01 to TC-10). The tests in `tests/test_research_graph.py` use a fake search client, so they run without network access or keys.

## Briefing contract

A briefing is valid only if it follows every rule below.

### 1. Sections

The briefing contains exactly these three `##` headings, in this order, with
no other `##` headings:

1. `## What the company does`
2. `## What changed in the last 90 days`
3. `## Three talking points`

Each section must have at least one line of content.

### 2. Talking points

The `## Three talking points` section contains exactly three numbered items,
`1.`, `2.` and `3.`, in that order.

### 3. Every factual sentence is sourced

Every sentence in the body (including each talking point) ends with a source
URL in parentheses, optionally followed by the closing period:

```
Gusto was founded in 2011 (https://gusto.com/about).
```

The cited URL must be one of the URLs that were actually fetched while
researching the briefing (`fetched_urls`). Citing a page that was not fetched
is not allowed.

### 4. Gaps

When the sources do not contain a fact, write this exact line on its own:

```
Not found in sources
```

No variations, no trailing period, no URL. This is the only line in the body
that may appear without a source. A section with nothing sourced may consist of
this line alone.

### 5. Closing line

The last non-empty line of the briefing is exactly:

```
Tool calls used: N
```

where `N` is a whole number.

### 6. Tool-call budget

A briefing may use at most **8** tool calls. `N` must be between 0 and 8.

## Rep usage instructions

## Run record

### Test suite

Run on 2026-10-16 with Python 3.13.2 on the commit that adds this record. Output of `pytest -v --no-header -p no:cacheprovider`, pasted in full and unedited. It covers both test files: `test_validator.py` (12 tests) and `test_research_graph.py` (18 tests).

```
============================= test session starts =============================
collecting ... collected 30 items

tests/test_research_graph.py::test_page_holds_url_and_text PASSED        [  3%]
tests/test_research_graph.py::test_timeout_field_is_bool PASSED          [  6%]
tests/test_research_graph.py::test_state_has_briefing_string PASSED      [ 10%]
tests/test_research_graph.py::test_pages_in_final_state_have_url_and_text PASSED [ 13%]
tests/test_research_graph.py::test_result_without_text_is_not_stored PASSED [ 16%]
tests/test_research_graph.py::test_planner_sets_queries PASSED           [ 20%]
tests/test_research_graph.py::test_search_node_increments_counter_itself PASSED [ 23%]
tests/test_research_graph.py::test_counter_equals_real_search_calls PASSED [ 26%]
tests/test_research_graph.py::test_route_continues_under_budget_without_timeout PASSED [ 30%]
tests/test_research_graph.py::test_route_exits_at_budget_alone PASSED    [ 33%]
tests/test_research_graph.py::test_route_exits_on_timeout_alone PASSED   [ 36%]
tests/test_research_graph.py::test_route_exits_on_empty_results_alone PASSED [ 40%]
tests/test_research_graph.py::test_graph_stops_at_budget PASSED          [ 43%]
tests/test_research_graph.py::test_timeout_sets_flag_and_goes_to_writer[builtin] PASSED [ 46%]
tests/test_research_graph.py::test_timeout_sets_flag_and_goes_to_writer[tavily] PASSED [ 50%]
tests/test_research_graph.py::test_empty_results_stop_search_and_go_to_writer PASSED [ 53%]
tests/test_research_graph.py::test_record_has_company_urls_and_stop_reason PASSED [ 56%]
tests/test_research_graph.py::test_each_run_writes_its_own_record PASSED [ 60%]
tests/test_validator.py::test_verdict_matches_expected[SB-01] PASSED     [ 63%]
tests/test_validator.py::test_verdict_matches_expected[SB-02] PASSED     [ 66%]
tests/test_validator.py::test_verdict_matches_expected[SB-03] PASSED     [ 70%]
tests/test_validator.py::test_verdict_matches_expected[SB-04] PASSED     [ 73%]
tests/test_validator.py::test_verdict_matches_expected[SB-05] PASSED     [ 76%]
tests/test_validator.py::test_verdict_matches_expected[SB-06] PASSED     [ 80%]
tests/test_validator.py::test_rejection_reason[SB-01] PASSED             [ 83%]
tests/test_validator.py::test_rejection_reason[SB-02] PASSED             [ 86%]
tests/test_validator.py::test_rejection_reason[SB-03] PASSED             [ 90%]
tests/test_validator.py::test_rejection_reason[SB-04] PASSED             [ 93%]
tests/test_validator.py::test_rejection_reason[SB-05] PASSED             [ 96%]
tests/test_validator.py::test_rejection_reason[SB-06] PASSED             [100%]

============================= 30 passed in 1.99s ==============================
```

### Validator on the six sample briefings

Output of `python -m briefing_validator tests/data/briefings.json`, pasted in full and unedited:

```
SB-01: VALID  (matches expected)
SB-02: VALID  (matches expected)
SB-03: VALID  (matches expected)
SB-04: INVALID  (matches expected)
  - headings must be exactly ['What the company does', 'What changed in the last 90 days', 'Three talking points'], got ['What the company does', 'Three talking points']
SB-05: INVALID  (matches expected)
  - sentence has no source URL: 'Mailchimp has been part of Intuit since its acquisition in 2021.'
SB-06: INVALID  (matches expected)
  - cited URL was not fetched: https://www.canva.com/enterprise/
```

### Live research run (TC-01, Allbirds)

Run on 2026-10-16 against Tavily with LangSmith tracing on. Command `python -m research_agent --company Allbirds --url https://www.allbirds.com`. The output is pasted in full and unedited, including the deprecation warning printed on stderr:

```
C:\Users\Parth\OneDrive\Desktop\sales agent\src\research_agent\__main__.py:28: DeprecationWarning: share_run() is deprecated and will be removed after Jan 31, 2027. Use client.runs.share.create() instead. See https://docs.langchain.com/langsmith/smithdb-sdk-migration-feedback#share-and-read-public-runs for the migration guide.
  return Client().share_run(run_id)
Allbirds (https://www.allbirds.com): 5 tool calls, stopped on queries_exhausted
  - https://www.allbirds.com/pages/our-story
  - https://www.allbirds.com/collections/womens
  - https://www.allbirds.com/collections/mens
  - https://www.nbcnews.com/tech/tech-news/allbirds-buzzy-shoe-startup-pivots-ai-rcna331943
  - https://www.cnbc.com/2026/04/15/allbirds-bird-stock-shoes-ai.html
  - https://www.bbc.com/news/articles/c98mrepzgj7o
  - https://www.allbirds.com/products/mens-runner-nz-slip-on-burnt-olive?a_ajs_event=Product+Clicked&a_ajs_prop_currency=USD&a_ajs_prop_currency_symbol=%24&a_ajs_prop_collection_handle=mens-loungers&a_ajs_prop_collection_name=Men%27s+Slip+Ons&a_ajs_prop_collection_parent=Mens&a_ajs_prop_collection_style_count=1&a_ajs_prop_collection_type=PARENT_COLLECTION&a_ajs_prop_collection_url=https%3A%2F%2Fwww.allbirds.com%2Fcollections%2Fmens-loungers&a_ajs_prop_list_id=135958495312&a_ajs_prop_is_markdown_collection=false&a_ajs_prop_products=a_ajs_prop_type_object%5B%7B%22category%22%3A%22Shoes%22%2C%22color_name%22%3A%22Burnt+Olive+%28Burnt+Olive+Sole%29%22%2C%22edition%22%3A%22Limited%22%2C%22gender%22%3A%22Mens%22%2C%22handle%22%3A%22mens-runner-nz-slip-on-burnt-olive%22%2C%22hue%22%3A%22Green%22%2C%22image_url%22%3A%22%2F%2Fwww.allbirds.com%2Fcdn%2Fshop%2Ffiles%2FA12471_26Q1_Runner-NZ-Slip-On-Burnt-Olive-Burnt-Olive-Sole_PDP_LEFT.png%3Fv%3D1768951144%22%2C%22material%22%3A%22Tree%22%2C%22name%22%3A%22Men%27s+Runner+NZ+Slip+On%22%2C%22on_sale%22%3Afalse%2C%22price%22%3A105%2C%22price_tier%22%3A%22msrp%22%2C%22product_id%22%3A%227205204000848%22%2C%22silhouette%22%3A%22Lounger%22%2C%22url%22%3A%22%2Fproducts%2Fmens-runner-nz-slip-on-burnt-olive%22%2C%22position%22%3A%222%22%7D%5D
  - https://www.allbirds.com/collections/sale-womens
  - https://www.allbirds.com/pages/introducing-the-tree-gliders
  - https://www.allbirds.com/blogs/news/allbirds-uber-eats-press-release
  - https://www.allbirds.com/pages/allbirds-terms-of-use-wholesale
  record: runs/20261016T061635Z_allbirds_2aa459e3.json
  trace: https://smith.langchain.com/public/3cab09a6-c550-4d90-a79d-d330788e416e/r
```

- Record: [runs/20261016T061635Z_allbirds_2aa459e3.json](runs/20261016T061635Z_allbirds_2aa459e3.json), committed as written.
- Public trace: https://smith.langchain.com/public/3cab09a6-c550-4d90-a79d-d330788e416e/r. I checked access with a request that sent no credentials: `GET https://api.smith.langchain.com/public/3cab09a6-c550-4d90-a79d-d330788e416e/run` returned HTTP 200 with the run `research: Allbirds`, status `success`.
- Check against `website_url`: 8 of the 11 fetched URLs are on `www.allbirds.com`. The other 3 (NBC News, CNBC, BBC) come from the news query, which is deliberately not limited to the company's domain.
