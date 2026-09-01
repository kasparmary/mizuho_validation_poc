"""
Sequence validator — confirms tags that ARE present appear in the same
relative order as rules.json's field_no (the guide's "No." column).

Canonical order is derived by sorting rules.json's tags on every run, never
hardcoded — this is the "no hardcoding the order" approach agreed on earlier.
The canonical list is then filtered down to only the tags present in this
specific file before comparing, since most tags are Optional and absent in
any given message.

Tags NOT recognized in rules.json (e.g. a tag from a different SWIFT message
type) are excluded from `actual_order` entirely — tag_identifier_validator.py
already diagnoses those clearly ("not a recognized MT700 field") and runs
before this check. Without this exclusion, an unrecognized tag desyncs the
position-by-position comparison below and produces a second, less accurate
"out of sequence" error for the same root cause.
"""

import logging
from typing import List
from src.models import ExtractedTag, ValidationResult


def check(extracted_tags: List[ExtractedTag], rules: dict, logger: logging.Logger = None) -> ValidationResult:
    logger = logger or logging.getLogger(__name__)

    # Derive canonical order fresh from rules.json every run (never cached/hardcoded).
    canonical_order = [t["tag"] for t in sorted(rules["tags"], key=lambda t: t["field_no"])]
    known_canonical_tags = set(canonical_order)

    actual_order = [t.canonical_tag for t in extracted_tags if t.canonical_tag in known_canonical_tags]
    present_set = set(actual_order)
    expected_order = [tag for tag in canonical_order if tag in present_set]

    logger.info(f"Expected order (filtered to present tags): {expected_order}")
    logger.info(f"Actual order (as extracted from file):     {actual_order}")

    if expected_order == actual_order:
        logger.info("Sequence check PASSED — tags appear in canonical field order")
        return ValidationResult(valid=True, errors=[])

    # Find first point of divergence for a precise, actionable error.
    for i, (expected_tag, actual_tag) in enumerate(zip(expected_order, actual_order)):
        if expected_tag != actual_tag:
            error = (
                f"Field out of sequence at position {i + 1}: expected '{expected_tag}' "
                f"(per MT700 field No. order), found '{actual_tag}'."
            )
            logger.error(error)
            return ValidationResult(valid=False, errors=[error])

    # Lists diverge only in length (e.g. extra/missing entries not caught above).
    error = (
        f"Sequence mismatch: expected order has {len(expected_order)} tag(s), "
        f"actual order has {len(actual_order)} tag(s)."
    )
    logger.error(error)
    return ValidationResult(valid=False, errors=[error])
