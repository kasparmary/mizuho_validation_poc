"""
Validation engine — orchestrates the full validation pipeline:

    extract -> presence check -> tag identifier check -> sequence check
    -> content check -> cross-field check

Tag identifier check runs BEFORE sequence deliberately: it's the check that
flags an unrecognized tag (e.g. a tag from a different SWIFT message type),
and sequence_validator excludes unrecognized tags from its own comparison
(see its module docstring) rather than re-diagnosing them as "out of
order" — so the unrecognized-tag diagnosis should surface first, not get
buried behind a second, less accurate error about the same root cause.

extract() also returns file-level structural_errors (pre-tag content,
mid-message blank lines) that aren't about any single tag — these are
folded into the tag identifier stage's result here, since that's already
the "structural legitimacy of the file" stage, rather than giving them a
separate pipeline stage of their own.

Runs all five checks regardless of earlier failures (rather than stopping at
the first one) so a single test run surfaces every problem in the file at
once — matching the soft-assertion, full-picture reporting approach
established for this suite.
"""

import json
import logging
from pathlib import Path

from src.models import ValidationReport
from src.extractor import extract
from src.validators import (
    presence_validator,
    sequence_validator,
    tag_identifier_validator,
    content_validator,
    cross_field_validator,
)


def load_rules(rules_path: str = "config/MT700/rules.json") -> dict:
    with open(rules_path, "r", encoding="utf-8") as f:
        return json.load(f)


def validate(file_path: str, rules: dict, logger: logging.Logger = None) -> ValidationReport:
    logger = logger or logging.getLogger(__name__)
    file_name = Path(file_path).name

    logger.info(f"===== Validating file: {file_name} =====")

    with open(file_path, "r", encoding="utf-8") as f:
        raw_text = f.read()

    extracted_tags, structural_errors = extract(raw_text)

    logger.info("--- Stage 1: Presence check ---")
    presence_result = presence_validator.check(extracted_tags, rules, logger)

    logger.info("--- Stage 2: Tag identifier check ---")
    tag_identifier_result = tag_identifier_validator.check(extracted_tags, rules, logger)
    if structural_errors:
        for msg in structural_errors:
            logger.error(msg)
        tag_identifier_result.errors.extend(structural_errors)
        tag_identifier_result.valid = False

    logger.info("--- Stage 3: Sequence check ---")
    sequence_result = sequence_validator.check(extracted_tags, rules, logger)

    logger.info("--- Stage 4: Content check ---")
    content_result = content_validator.check(extracted_tags, rules, logger)

    logger.info("--- Stage 5: Cross-field check ---")
    cross_field_result = cross_field_validator.check(extracted_tags, rules, logger)

    report = ValidationReport(
        file_name=file_name,
        extracted_tags=extracted_tags,
        presence_result=presence_result,
        sequence_result=sequence_result,
        tag_identifier_result=tag_identifier_result,
        content_result=content_result,
        cross_field_result=cross_field_result,
    )

    logger.info(f"===== Overall result for {file_name}: {'VALID' if report.overall_valid else 'INVALID'} =====")
    return report
