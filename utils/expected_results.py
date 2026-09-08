"""
Expected outcomes for the active message type's validation scenarios,
covering file structure (presence/sequence/tag-identifier), field content
(format/codes/NVR on tag values), and cross-field rules (C1/C2/C3/U1) —
engine.validate() runs all of these in one pass, so they all live in a
single scenario list here.

Scenario data lives in a per-message-type CSV (e.g. data/MT700/expected_
results.csv), NOT as Python literals — per manager review Phase 3, item
#15: a plain data file is reviewable by non-developer stakeholders
(business analysts, testers, auditors) without Python knowledge, where a
Python dataclass list was not. Adding or editing a scenario is now a
spreadsheet edit, not a code change.

WHICH CSV gets loaded is resolved once, at import time, via
utils.message_type_config.resolve_active_message_type() — the MT_TARGET
env var, or config/message_types.json's "default" if unset. This has to
happen at import time (not inside a fixture) because pytest.mark.parametrize
needs the concrete scenario list at collection time, before any fixture
resolves.

Still deliberately NOT read from the xlsx test matrix (unrelated decision,
unchanged): the xlsx is kept as a separate design/review artifact, not a
live test dependency.

Each row: test_id, file_name, scenario (description), expected_valid,
expected_error_substring (blank for positive cases; for negative cases a
substring that MUST appear somewhere in the report's combined errors, so a
test can't pass for the wrong reason), is_edge_case.
"""

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from utils.message_type_config import resolve_active_message_type

_PROJECT_ROOT = Path(__file__).parent.parent
ACTIVE_MESSAGE_TYPE = resolve_active_message_type()
_CSV_PATH = _PROJECT_ROOT / ACTIVE_MESSAGE_TYPE.scenarios_path


@dataclass
class ExpectedOutcome:
    test_id: str
    file_name: str
    scenario: str
    expected_valid: bool
    expected_error_substring: Optional[str] = None
    is_edge_case: bool = False


def _load_scenarios(csv_path: Path) -> list:
    scenarios = []
    with open(csv_path, "r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            scenarios.append(ExpectedOutcome(
                test_id=row["test_id"],
                file_name=row["file_name"],
                scenario=row["scenario"],
                expected_valid=row["expected_valid"] == "True",
                expected_error_substring=row["expected_error_substring"] or None,
                is_edge_case=row["is_edge_case"] == "True",
            ))
    return scenarios


FILE_STRUCTURE_SCENARIOS = _load_scenarios(_CSV_PATH)
