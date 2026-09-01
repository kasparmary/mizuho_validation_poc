"""
Cross-field validator — evaluates message-LEVEL rules that compare DIFFERENT
tags against each other (rules.json's `message_level_network_validated_rules`,
e.g. SWIFT's C1/C2/C3), as opposed to every other validator in this package
(presence/sequence/tag identifier/content) which only ever looks at one
tag's own identifier or value at a time.

Driven entirely by rules.json, not hardcoded per rule_id — any future
message-level rule expressed with one of the `dependency_type`s below is
picked up automatically, no code change here. This mirrors how
presence/sequence/tag identifier are already rules.json-driven; content_validator
is the deliberate exception (one function per tag) because per-tag VALUE
shapes genuinely differ, but cross-field PRESENCE relationships reduce to a
small, enumerable set of patterns, so a generic interpreter is the right
call here.
"""

import logging
from typing import List, Optional
from src.models import ExtractedTag, ValidationResult


def _present_tags(extracted_tags: List[ExtractedTag]) -> set:
    return {t.canonical_tag for t in extracted_tags}


def _check_co_presence(rule: dict, present: set) -> Optional[str]:
    involved = rule["tags_involved"]
    present_involved = [t for t in involved if t in present]
    if present_involved and len(present_involved) != len(involved):
        missing = [t for t in involved if t not in present]
        return (
            f"Rule {rule['rule_id']}: {rule['text']} "
            f"Present: {present_involved}, missing: {missing} [{rule['error_code']}]."
        )
    return None


def _check_mutual_exclusion(rule: dict, present: set) -> Optional[str]:
    involved = rule["tags_involved"]
    present_involved = [t for t in involved if t in present]
    if len(present_involved) > 1:
        return (
            f"Rule {rule['rule_id']}: {rule['text']} "
            f"Present together: {present_involved} [{rule['error_code']}]."
        )
    return None


def _check_mutual_exclusion_grouped(rule: dict, present: set) -> Optional[str]:
    active_groups = [g for g in rule["groups"] if any(t in present for t in g)]
    if len(active_groups) > 1:
        return (
            f"Rule {rule['rule_id']}: {rule['text']} "
            f"More than one group present: {active_groups} [{rule['error_code']}]."
        )
    return None


_EVALUATORS = {
    "co_presence": _check_co_presence,
    "mutual_exclusion": _check_mutual_exclusion,
    "mutual_exclusion_grouped": _check_mutual_exclusion_grouped,
}


def check(extracted_tags: List[ExtractedTag], rules: dict, logger: logging.Logger = None) -> ValidationResult:
    logger = logger or logging.getLogger(__name__)
    present = _present_tags(extracted_tags)

    errors: List[str] = []
    for rule in rules.get("message_level_network_validated_rules", []):
        evaluator = _EVALUATORS.get(rule["dependency_type"])
        if evaluator is None:
            logger.warning(
                f"Rule {rule['rule_id']}: unknown dependency_type "
                f"'{rule['dependency_type']}', skipped."
            )
            continue

        error = evaluator(rule, present)
        if error:
            logger.error(error)
            errors.append(error)
        else:
            logger.debug(f"Rule {rule['rule_id']} PASSED")

    if errors:
        return ValidationResult(valid=False, errors=errors)

    logger.info("Cross-field check PASSED — all message-level rules satisfied")
    return ValidationResult(valid=True, errors=[])
