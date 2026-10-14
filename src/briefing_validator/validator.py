"""Checks a sales call briefing against the contract in README.md."""

import re
from dataclasses import dataclass, field

REQUIRED_HEADINGS = [
    "What the company does",
    "What changed in the last 90 days",
    "Three talking points",
]
GAP_LINE = "Not found in sources"
TOOL_CALL_BUDGET = 8

CLOSING_RE = re.compile(r"^Tool calls used: (\d+)$")
NUMBERED_RE = re.compile(r"^(\d+)\.\s+(.*)$")
CITED_SENTENCE_RE = re.compile(r"\((https?://[^\s()]+)\)\.?$")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")


@dataclass
class Result:
    valid: bool
    errors: list[str] = field(default_factory=list)


def _split_sections(lines):
    """Return ({heading: [content lines]}, [headings in order], [lines before first heading])."""
    sections, order, preamble = {}, [], []
    current = None
    for line in lines:
        if line.startswith("## "):
            current = line[3:].strip()
            order.append(current)
            sections[current] = []
        elif current is None:
            preamble.append(line)
        else:
            sections[current].append(line)
    return sections, order, preamble


def validate(briefing_markdown: str, fetched_urls: list[str]) -> Result:
    errors = []
    lines = [line.rstrip() for line in briefing_markdown.strip().splitlines()]

    # Rule 5 and 6: closing line and budget.
    closing = CLOSING_RE.match(lines[-1]) if lines else None
    if not closing:
        errors.append("last line must be 'Tool calls used: N'")
    else:
        lines = lines[:-1]
        used = int(closing.group(1))
        if used > TOOL_CALL_BUDGET:
            errors.append(f"used {used} tool calls, budget is {TOOL_CALL_BUDGET}")

    # Rule 1: sections.
    sections, order, preamble = _split_sections(lines)
    if any(line.strip() for line in preamble):
        errors.append("content found before the first section heading")
    if order != REQUIRED_HEADINGS:
        errors.append(f"headings must be exactly {REQUIRED_HEADINGS}, got {order}")

    allowed = set(fetched_urls)
    for heading, content in sections.items():
        body = [line.strip() for line in content if line.strip()]
        if not body:
            errors.append(f"section '{heading}' is empty")

        # Rule 2: talking points.
        if heading == "Three talking points":
            numbers = [m.group(1) for m in map(NUMBERED_RE.match, body) if m]
            if numbers != ["1", "2", "3"]:
                errors.append(f"talking points must be numbered 1, 2, 3, got {numbers}")

        # Rules 3 and 4: sourcing and gap line.
        for line in body:
            if line == GAP_LINE:
                continue
            if line.lower().startswith(GAP_LINE.lower()):
                errors.append(f"gap line must be exactly '{GAP_LINE}': {line!r}")
                continue
            numbered = NUMBERED_RE.match(line)
            text = numbered.group(2) if numbered else line
            for sentence in SENTENCE_SPLIT_RE.split(text):
                cited = CITED_SENTENCE_RE.search(sentence)
                if not cited:
                    errors.append(f"sentence has no source URL: {sentence!r}")
                elif cited.group(1) not in allowed:
                    errors.append(f"cited URL was not fetched: {cited.group(1)}")

    return Result(valid=not errors, errors=errors)
