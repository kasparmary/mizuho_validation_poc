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

dependency_types:
  - co_presence: if any of tags_involved is present, all must be (C1).
  - mutual_exclusion: at most one of tags_involved may be present (C3).
  - mutual_exclusion_grouped: at most one of groups[] may have any member
    present (C2). If the rule has a `suppressed_by: "<rule_id>"` key and
    that other rule already failed AND its tags_involved overlaps a group,
    that group is excluded from the active-group count — this implements
    C2's own `"note"` field ("C1 governs internal co-presence of the first
    group; evaluate C1 before C2") so C1 and C2 don't both fire for the same
    root cause (a partially-present 42C/42a group also triggering C2's
    multi-group check on top of C1's own co-presence complaint).
  - conditional_presence: if trigger_tag's VALUE is one of trigger_values,
    required_tag must be present. Unlike the three above, this depends on a
    tag's value, not just its presence — e.g. "58a must be present if tag 49
    is MAY ADD or CONFIRM" (this rule is not an official SWIFT 'C' number;
    it originates from tag 58a's usage_rules[0] in rules.json, promoted to
    message level since it's a cross-field concern).
"""

import logging
from typing import List, Optional
from src.models import ExtractedTag, ValidationResult


def _present_tags(extracted_tags: List[ExtractedTag]) -> set:
    return {t.canonical_tag for t in extracted_tags}


def _tag_values(extracted_tags: List[ExtractedTag]) -> dict:
    return {t.canonical_tag: t.value for t in extracted_tags}


def _check_co_presence(rule: dict, present: set, tag_values: dict, rules_by_id: dict, failed_rule_ids: set) -> Optional[str]:
    involved = rule["tags_involved"]
    present_involved = [t for t in involved if t in present]
    if present_involved and len(present_involved) != len(involved):
        missing = [t for t in involved if t not in present]
        return (
            f"Rule {rule['rule_id']}: {rule['text']} "
            f"Present: {present_involved}, missing: {missing} [{rule['error_code']}]."
        )
    return None


def _check_mutual_exclusion(rule: dict, present: set, tag_values: dict, rules_by_id: dict, failed_rule_ids: set) -> Optional[str]:
    involved = rule["tags_involved"]
    present_involved = [t for t in involved if t in present]
    if len(present_involved) > 1:
        return (
            f"Rule {rule['rule_id']}: {rule['text']} "
            f"Present together: {present_involved} [{rule['error_code']}]."
        )
    return None


def _check_mutual_exclusion_grouped(rule: dict, present: set, tag_values: dict, rules_by_id: dict, failed_rule_ids: set) -> Optional[str]:
    suppressor_id = rule.get("suppressed_by")
    suppressor_failed = bool(suppressor_id) and suppressor_id in failed_rule_ids
    suppressor_tags = set(rules_by_id[suppressor_id]["tags_involved"]) if suppressor_failed else set()

    active_groups = []
    for g in rule["groups"]:
        if not any(t in present for t in g):
            continue
        if suppressor_failed and set(g) & suppressor_tags:
            continue  # this group's anomaly is already explained by the earlier-failed suppressor rule
        active_groups.append(g)

    if len(active_groups) > 1:
        return (
            f"Rule {rule['rule_id']}: {rule['text']} "
            f"More than one group present: {active_groups} [{rule['error_code']}]."
        )
    return None


def _check_conditional_presence(rule: dict, present: set, tag_values: dict, rules_by_id: dict, failed_rule_ids: set) -> Optional[str]:
    """If trigger_tag's value is one of trigger_values, required_tag must be
    present — e.g. C4-style usage rules like '58a must be present if tag 49
    is MAY ADD or CONFIRM', which (unlike C1/C2/C3) depend on a tag's VALUE,
    not just its presence."""
    trigger_tag = rule["trigger_tag"]
    required_tag = rule["required_tag"]

    trigger_value = tag_values.get(trigger_tag)
    if trigger_value not in rule["trigger_values"]:
        return None

    if required_tag not in present:
        return (
            f"Rule {rule['rule_id']}: {rule['text']} "
            f"Tag '{trigger_tag}' is '{trigger_value}' but tag '{required_tag}' "
            f"is absent [{rule['error_code']}]."
        )
    return None


_EVALUATORS = {
    "co_presence": _check_co_presence,
    "mutual_exclusion": _check_mutual_exclusion,
    "mutual_exclusion_grouped": _check_mutual_exclusion_grouped,
    "conditional_presence": _check_conditional_presence,
}


def check(extracted_tags: List[ExtractedTag], rules: dict, logger: logging.Logger = None) -> ValidationResult:
    logger = logger or logging.getLogger(__name__)
    present = _present_tags(extracted_tags)
    tag_values = _tag_values(extracted_tags)

    all_rules = rules.get("message_level_network_validated_rules", [])
    rules_by_id = {r["rule_id"]: r for r in all_rules}
    failed_rule_ids: set = set()

    errors: List[str] = []
    for rule in all_rules:
        evaluator = _EVALUATORS.get(rule["dependency_type"])
        if evaluator is None:
            logger.warning(
                f"Rule {rule['rule_id']}: unknown dependency_type "
                f"'{rule['dependency_type']}', skipped."
            )
            continue

        error = evaluator(rule, present, tag_values, rules_by_id, failed_rule_ids)
        if error:
            failed_rule_ids.add(rule["rule_id"])
            logger.error(error)
            errors.append(error)
        else:
            logger.debug(f"Rule {rule['rule_id']} PASSED")

    if errors:
        return ValidationResult(valid=False, errors=errors)

    logger.info("Cross-field check PASSED — all message-level rules satisfied")
    return ValidationResult(valid=True, errors=[])
