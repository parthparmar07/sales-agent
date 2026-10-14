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

Run on 2026-10-14 with Python 3.13.2. Both blocks are pasted output, unedited.

`pytest -v` checks each verdict against `expected_valid` and each rejection reason against an exact expected error:

```
tests/test_validator.py::test_verdict_matches_expected[SB-01] PASSED     [  8%]
tests/test_validator.py::test_verdict_matches_expected[SB-02] PASSED     [ 16%]
tests/test_validator.py::test_verdict_matches_expected[SB-03] PASSED     [ 25%]
tests/test_validator.py::test_verdict_matches_expected[SB-04] PASSED     [ 33%]
tests/test_validator.py::test_verdict_matches_expected[SB-05] PASSED     [ 41%]
tests/test_validator.py::test_verdict_matches_expected[SB-06] PASSED     [ 50%]
tests/test_validator.py::test_rejection_reason[SB-01] PASSED             [ 58%]
tests/test_validator.py::test_rejection_reason[SB-02] PASSED             [ 66%]
tests/test_validator.py::test_rejection_reason[SB-03] PASSED             [ 75%]
tests/test_validator.py::test_rejection_reason[SB-04] PASSED             [ 83%]
tests/test_validator.py::test_rejection_reason[SB-05] PASSED             [ 91%]
tests/test_validator.py::test_rejection_reason[SB-06] PASSED             [100%]
============================= 12 passed in 0.05s ==============================
```

`python -m briefing_validator tests/data/briefings.json` prints the validator's own verdicts and reasons:

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
