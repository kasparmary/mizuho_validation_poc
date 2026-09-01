"""
Tag identifier validator — three related structural checks that all operate
on the raw list of extracted tags, run before any per-tag content validation:

1. No tag number repeats (MT700 has no repeating field groups).
2. Every extracted tag number corresponds to a real, known MT700 field
   (catches typos / unrecognized tags, or a tag from a different SWIFT
   message type like "99Z").
3. Every raw tag identifier is uppercase, matching real SWIFT wire format
   (catches non-standard casing like "41a" instead of "41A").

Kept together in one validator because all three are about the STRUCTURAL
LEGITIMACY of the tag identifiers themselves, prior to and independent of
each tag's content — and all three iterate the file's EXTRACTED tags (not
rules.json's tag list), unlike presence_validator, which iterates rules.json's
mandatory tags asking whether each is present. Runs before sequence_validator
so an unrecognized tag is diagnosed clearly here first, rather than also
(or instead) showing up as a confusing "out of sequence" error there.
"""

import logging
from typing import List
from src.models import ExtractedTag, ValidationResult


def check(extracted_tags: List[ExtractedTag], rules: dict, logger: logging.Logger = None) -> ValidationResult:
    logger = logger or logging.getLogger(__name__)

    known_canonical_tags = {t["tag"] for t in rules["tags"]}
    errors: List[str] = []

    seen_canonical = set()
    for t in extracted_tags:
        # --- Check 1: duplicates ---
        if t.canonical_tag in seen_canonical:
            msg = f"Tag '{t.raw_tag}' (line {t.line_number}) is a duplicate of an earlier '{t.canonical_tag}' tag."
            logger.error(msg)
            errors.append(msg)
        else:
            seen_canonical.add(t.canonical_tag)

        # --- Check 2: unknown tag ---
        if t.canonical_tag not in known_canonical_tags:
            msg = f"Tag '{t.raw_tag}' (line {t.line_number}) is not a recognized MT700 field."
            logger.error(msg)
            errors.append(msg)

        # --- Check 3: uppercase identifier convention ---
        if t.raw_tag != t.raw_tag.upper():
            msg = (
                f"Tag '{t.raw_tag}' (line {t.line_number}) is not uppercase — "
                f"SWIFT wire-format tag identifiers must be uppercase (e.g. '41A', not '41a')."
            )
            logger.warning(msg)
            errors.append(msg)
        else:
            logger.debug(f"Tag '{t.raw_tag}' passed identifier checks (unique, known, uppercase)")

    if errors:
        return ValidationResult(valid=False, errors=errors)

    logger.info("Tag identifier check PASSED — all tags unique, recognized, and correctly cased")
    return ValidationResult(valid=True, errors=[])
