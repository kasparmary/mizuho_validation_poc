"""
Presence validator — confirms every Mandatory MT700 tag is present with a
non-empty value.

Deliberately reports ALL missing/empty mandatory tags in one pass, not just
the first one found — a single generic "mandatory tag missing" error was
flagged early on as a diagnostic dead-end; this fixes that.
"""

import logging
from typing import List
from src.models import ExtractedTag, ValidationResult


def check(extracted_tags: List[ExtractedTag], rules: dict, logger: logging.Logger = None) -> ValidationResult:
    logger = logger or logging.getLogger(__name__)

    mandatory_tags = [t["tag"] for t in rules["tags"] if t["presence"] == "Mandatory"]
    logger.info(f"Presence check: {len(mandatory_tags)} mandatory tags required: {mandatory_tags}")

    present_by_canonical = {t.canonical_tag: t.value for t in extracted_tags}

    missing = []
    for tag in mandatory_tags:
        value = present_by_canonical.get(tag)
        if value is None:
            missing.append(tag)
            logger.warning(f"Mandatory tag '{tag}' is absent from the file")
        elif value.strip() == "":
            missing.append(tag)
            logger.warning(f"Mandatory tag '{tag}' is present but has an empty value")
        else:
            logger.debug(f"Mandatory tag '{tag}' present with value: {value!r}")

    if missing:
        error = f"Mandatory tag(s) missing or empty: {', '.join(missing)}. File is not valid."
        logger.error(error)
        return ValidationResult(valid=False, errors=[error])

    logger.info("Presence check PASSED — all mandatory tags present and non-empty")
    return ValidationResult(valid=True, errors=[])
