import json
from pathlib import Path

import pytest

from briefing_validator.validator import validate

SAMPLES = json.loads((Path(__file__).parent / "data" / "briefings.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("sample", SAMPLES, ids=[s["sample_id"] for s in SAMPLES])
def test_verdict_matches_expected(sample):
    result = validate(sample["briefing_markdown"], sample["fetched_urls"])
    assert result.valid == sample["expected_valid"], result.errors
