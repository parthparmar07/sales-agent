"""Validate every briefing in a JSON file: python -m briefing_validator path/to/briefings.json"""

import json
import sys
from pathlib import Path

from briefing_validator.validator import validate


def main(path: str) -> int:
    samples = json.loads(Path(path).read_text(encoding="utf-8"))
    mismatches = 0
    for sample in samples:
        result = validate(sample["briefing_markdown"], sample["fetched_urls"])
        expected = sample.get("expected_valid")
        match = "" if expected is None else ("  (matches expected)" if result.valid == expected else "  (MISMATCH)")
        mismatches += expected is not None and result.valid != expected
        print(f"{sample['sample_id']}: {'VALID' if result.valid else 'INVALID'}{match}")
        for error in result.errors:
            print(f"  - {error}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
