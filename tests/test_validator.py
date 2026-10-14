import json
from pathlib import Path

import pytest

from briefing_validator.validator import validate

SAMPLES = json.loads((Path(__file__).parent / "data" / "briefings.json").read_text(encoding="utf-8"))

# The single error each invalid sample must be rejected for. Valid samples must have no errors.
EXPECTED_ERRORS = {
    "SB-04": "headings must be exactly ['What the company does', 'What changed in the last 90 days', "
    "'Three talking points'], got ['What the company does', 'Three talking points']",
    "SB-05": "sentence has no source URL: 'Mailchimp has been part of Intuit since its acquisition in 2021.'",
    "SB-06": "cited URL was not fetched: https://www.canva.com/enterprise/",
}


@pytest.mark.parametrize("sample", SAMPLES, ids=[s["sample_id"] for s in SAMPLES])
def test_verdict_matches_expected(sample):
    result = validate(sample["briefing_markdown"], sample["fetched_urls"])
    assert result.valid == sample["expected_valid"], result.errors


@pytest.mark.parametrize("sample", SAMPLES, ids=[s["sample_id"] for s in SAMPLES])
def test_rejection_reason(sample):
    result = validate(sample["briefing_markdown"], sample["fetched_urls"])
    expected = [EXPECTED_ERRORS[sample["sample_id"]]] if sample["sample_id"] in EXPECTED_ERRORS else []
    assert result.errors == expected
