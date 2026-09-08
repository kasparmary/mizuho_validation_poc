"""
Validation test suite for the active message type (see
utils.message_type_config — MT_TARGET env var, or config/message_types.json's
"default").

One parametrized test function drives every scenario: each points at an input
file and an expected outcome, so the test logic itself never varies — only
the input file and expected outcome do (this is the "script agnostic, data
configurable" shape applied at the test level). Scenarios cover file
structure (presence/sequence/tag identifier), field content (format/codes/
NVR on tag values), and cross-field rules, since engine.validate() runs all
five checks in one pass against every file. This test function has no
message-type-specific logic anywhere — which tags/rules/fixtures apply is
entirely a property of the `rules` fixture and `DATA_DIR`, both resolved
from the registry, not this file.

Each test attaches, as Allure evidence:
  1. The execution log (via the `test_logger` fixture, attached in conftest.py)
  2. The raw input file (exactly what was fed to the engine)
  3. The full validation report (presence/sequence/duplicate/content results)
"""

import json
import allure
import pytest

from src.engine import validate
from utils.expected_results import FILE_STRUCTURE_SCENARIOS, ACTIVE_MESSAGE_TYPE

DATA_DIR = ACTIVE_MESSAGE_TYPE.data_dir


def _scenario_id(scenario):
    return f"{scenario.test_id}_{scenario.file_name}"


@allure.feature("File Structure Validation")
@pytest.mark.parametrize(
    "scenario",
    FILE_STRUCTURE_SCENARIOS,
    ids=[_scenario_id(s) for s in FILE_STRUCTURE_SCENARIOS],
)
def test_file_structure_validation(scenario, rules, test_logger):
    # Epic must be set via allure.dynamic here, not the @allure.epic(...)
    # decorator — a decorator is evaluated once for the whole parametrized
    # function and can't vary per scenario/message type; dynamic.epic can.
    allure.dynamic.epic(f"{ACTIVE_MESSAGE_TYPE.message_type} Validation")

    if scenario.is_edge_case:
        story = "Edge Cases"
    elif scenario.expected_valid:
        story = "Positive Cases"
    else:
        story = "Negative Cases"
    allure.dynamic.story(story)

    allure.dynamic.title(f"{scenario.test_id}: {scenario.scenario}")
    allure.dynamic.description(
        f"**File:** `{scenario.file_name}`\n\n"
        f"**Expected valid:** {scenario.expected_valid}\n\n"
        f"**Expected error contains:** {scenario.expected_error_substring or 'N/A (positive case)'}"
    )

    test_logger.info(f"Test ID: {scenario.test_id} — {scenario.scenario}")
    file_path = f"{DATA_DIR}/{scenario.file_name}"

    with allure.step(f"Run validation engine against {scenario.file_name}"):
        report = validate(file_path, rules, logger=test_logger)

    with allure.step("Attach raw input file"):
        allure.attach.file(
            file_path,
            name=f"Raw Input ({scenario.file_name})",
            attachment_type=allure.attachment_type.TEXT,
        )

    with allure.step("Attach validation report"):
        report_dict = {
            "file_name": report.file_name,
            "overall_valid": report.overall_valid,
            "presence": {"valid": report.presence_result.valid, "errors": report.presence_result.errors},
            "sequence": {"valid": report.sequence_result.valid, "errors": report.sequence_result.errors},
            "tag_identifier": {"valid": report.tag_identifier_result.valid, "errors": report.tag_identifier_result.errors},
            "content": {"valid": report.content_result.valid, "errors": report.content_result.errors},
            "cross_field": {"valid": report.cross_field_result.valid, "errors": report.cross_field_result.errors},
        }
        allure.attach(
            json.dumps(report_dict, indent=2),
            name="Validation Report",
            attachment_type=allure.attachment_type.JSON,
        )

    with allure.step(f"Assert overall_valid == {scenario.expected_valid}"):
        assert report.overall_valid == scenario.expected_valid, (
            f"{scenario.test_id}: expected overall_valid={scenario.expected_valid}, "
            f"got {report.overall_valid}. Errors: {report.all_errors()}"
        )

    if scenario.expected_error_substring:
        with allure.step(f"Assert error mentions '{scenario.expected_error_substring}'"):
            combined_errors = " | ".join(report.all_errors())
            assert scenario.expected_error_substring.lower() in combined_errors.lower(), (
                f"{scenario.test_id}: expected an error mentioning "
                f"'{scenario.expected_error_substring}', got: {combined_errors}"
            )

    test_logger.info(f"Test ID: {scenario.test_id} — PASSED")
