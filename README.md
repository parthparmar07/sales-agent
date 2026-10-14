# Sales Call Briefing Validator

A sales call briefing is a short Markdown document a rep reads before a call.
This repo defines exactly what a valid briefing looks like (the contract below)
and ships a validator that checks briefings against it.

## Setup

```
pip install -r requirements.txt
cp .env.example .env   # then fill in your keys
pytest -v
```

`.env` holds `OPENROUTER_API_KEY`, `TAVILY_API_KEY` and `LANGSMITH_API_KEY`.
It is git-ignored; only `.env.example` (empty values) is committed.

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

Run on 2026-10-14 with Python 3.13.2, command `pytest -v`:

```
tests/test_validator.py::test_verdict_matches_expected[SB-01] PASSED     [ 16%]
tests/test_validator.py::test_verdict_matches_expected[SB-02] PASSED     [ 33%]
tests/test_validator.py::test_verdict_matches_expected[SB-03] PASSED     [ 50%]
tests/test_validator.py::test_verdict_matches_expected[SB-04] PASSED     [ 66%]
tests/test_validator.py::test_verdict_matches_expected[SB-05] PASSED     [ 83%]
tests/test_validator.py::test_verdict_matches_expected[SB-06] PASSED     [100%]
============================== 6 passed in 0.04s ==============================
```

Why the three invalid samples fail:

- SB-04: missing the `## What changed in the last 90 days` section.
- SB-05: "Mailchimp has been part of Intuit since its acquisition in 2021." has no source URL.
- SB-06: cites `https://www.canva.com/enterprise/`, which is not in its fetched URLs.
