"""
Content validator — confirms a tag's VALUE conforms to its format, code
list, and rules[] constraints from rules.json, as opposed to the file-
structure validators (presence/sequence/tag identifier) which only ever
look at tag identifiers, never the values inside them.

Rules-driven engine (manager review, docs/mizuho-review-suggestions.xlsx
item #1; full design and migration history in
docs/content-validator-shape-taxonomy.md). Every tag has a `shape`
descriptor (pure parsing metadata — how to decompose its value into named
subfields: separators, positional lengths, BIC-branch detection, etc.) and
a `rules[]` array (one object per atomic constraint — `rule_id`,
`subfield`, `rule_type`, `constraint`, `severity`, `error_code`,
`source_section`, `condition`, `depends_on`, `description`). `check()`
dispatches by `shape["kind"]` to a `_parse_*` function (decompose), then
runs `_evaluate_rules()` against the result — no per-tag Python function,
and no per-tag hardcoded error-code resolution: the code shown for a
violation comes directly from whichever rule fired.

FULL SCOPE: all 39 MT700 tags have both `shape` and `rules[]` —
find_uncovered_tags_with_rules() returns empty. `network_validated_rules[]`
(the pre-rules[] schema) has been fully retired; no tag carries it anymore.

Shape kinds: text, enum, date_yymmdd, multiline, currency_amount,
bic_or_name, composite, conditional_narrative, structured_charges_or_info.
The last one (71D, 72Z) is the one exception to "decompose then check
atomic rules": it's a stateful per-line state machine (code/continuation/
narrative lines, narrative must be last) with no fixed set of independent
subfields, so its `_parse_structured_charges_or_info()` does the full
check itself (wrapping the one remaining `_interp_*`-style function,
`_interp_structured_charges_or_info`) and its `rules[]` is a deliberate
empty list, not a gap.

`codes[].meaning` is shown in enum violation messages. A tag whose
rules.json entry has `"verified": false` triggers a logged warning when
its rule is applied, since the data itself flags that entry as not
independently re-confirmed.

Deliberately OUT OF SCOPE:
  - C1 (42C/42a co-presence), C2 (42C+42a / 42M / 42P mutual exclusion), C3
    (44C/44D mutual exclusion), and U1 (58a must be present if 49 is MAY ADD
    or CONFIRM) — message-level rules, handled by cross_field_validator.py.
  - Only 1 of ~10+ distinct `usage_rules[].depends_on` cross-field
    relationships (58a->49, promoted to U1) is automated. The rest remain a
    separate, unscoped follow-up.
  - No shape kind validates character-set membership (that a `z`/`x`-charset
    field's actual characters are valid SWIFT characters) — only
    length/line-count/position are checked, for every kind.
  - Every `bic_or_name` tag's `rules[]` documents that a BIC must be
    *registered* (T27/T28/T29/T45/C05), but only tag 51a actually checks one
    against something (`config/bic_directory_sample.json` — a small,
    explicitly illustrative reference set, not a real SWIFT directory, via
    `_rule_check_bic_directory_lookup`/`_check_bic_directory`). Every other
    `bic_or_name` tag only verifies BIC *shape* (8 or 11 alphanumeric
    characters) — documented directly in each of those tags' own `rules[]`
    entries (`rule_type: "external_reference"`, `constraint.reference`
    states the gap), not a silent omission.
"""

import json
import logging
import re
from datetime import date
from pathlib import Path
from typing import List, Optional, Tuple
from src.models import ExtractedTag, ValidationResult

# Full ISO 4217 active-currency minor-unit (decimal) precision table, read
# from config/iso4217.json (source: https://en.wikipedia.org/wiki/ISO_4217)
# — a general reference dataset, not MT700-specific, kept separate from
# rules.json.
_ISO4217_PATH = Path(__file__).resolve().parents[2] / "config" / "iso4217.json"


def _load_iso4217_decimals() -> dict:
    with open(_ISO4217_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["decimals"]


_ISO4217_DECIMALS = _load_iso4217_decimals()

# Small illustrative BIC reference set (config/bic_directory_sample.json) —
# NOT a real SWIFT BIC directory; this project has no live network/directory
# access. Exists only so error codes T27/T28/T29/T45/C05 can be independently
# exercised in local tests, instead of collapsing into one bundled label the
# way every other bic_or_name tag's shape-only check still does. Opt-in per
# tag via shape["bic_directory_check"] — see _interp_bic_or_name.
_BIC_DIRECTORY_PATH = Path(__file__).resolve().parents[2] / "config" / "bic_directory_sample.json"


def _load_bic_directory() -> dict:
    with open(_BIC_DIRECTORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["institutions"]


_BIC_DIRECTORY = _load_bic_directory()


def _check_bic_directory(value: str) -> Optional[dict]:
    """Looks an already shape-valid BIC (8 or 11 alnum chars) up against the
    small illustrative directory above, returning a violation with the
    single, specific error code that applies — or None if the BIC is fully
    recognized, live, correctly-branched, and a financial institution."""
    core, branch = value[:8], value[8:] or None
    institution = _BIC_DIRECTORY.get(core)

    if institution is None:
        return _violation(
            f"BIC core '{core}' is not a recognized institution in the local BIC reference",
            code_override="T27",
        )
    if branch and branch not in institution["valid_branch_codes"]:
        return _violation(
            f"BIC '{value}' has a recognized institution core but branch code '{branch}' "
            f"is not registered for {core}",
            code_override="T28",
        )
    if institution["status"] == "test_training":
        return _violation(f"BIC '{value}' is registered but is a Test & Training destination, not live", code_override="T29")
    if institution["status"] != "live":
        return _violation(f"BIC '{value}' failed general registration validation (status: {institution['status']})", code_override="T45")
    if institution["category"] != "financial_institution":
        return _violation(
            f"BIC '{value}' is registered as a '{institution['category']}' entity, not a financial institution",
            code_override="C05",
        )
    return None


def _is_valid_yymmdd(date_str: str) -> bool:
    """6!n date validity — used by date_yymmdd directly, and by composite's
    date_yymmdd subfield type."""
    if not (len(date_str) == 6 and date_str.isdigit()):
        return False
    yy, mm, dd = int(date_str[0:2]), int(date_str[2:4]), int(date_str[4:6])
    try:
        date(2000 + yy, mm, dd)
        return True
    except ValueError:
        return False


def _check_lines(lines: List[str], max_lines: int, max_line_len: int) -> Optional[str]:
    """Shared line-count + per-line-length check, used by multiline and by
    bic_or_name's Option D name/address block."""
    if len(lines) > max_lines:
        return f"exceeds the {max_lines}-line maximum ({max_lines}*{max_line_len}x)"
    for line in lines:
        if len(line) > max_line_len:
            return f"line '{line}' exceeds {max_line_len} characters ({max_lines}*{max_line_len}x)"
    return None


def _violation(detail: str, code_override: Optional[str] = None) -> dict:
    """What a rule check or a parser's structural failure returns. `detail`
    is the human-readable reason; `code_override` is the bracketed error
    code shown alongside it (None for constraints with no official SWIFT
    NVR backing, or the literal "ADVISORY" label for a severity="advisory"
    rule with no error_code — see _evaluate_rules)."""
    return {"detail": detail, "code_override": code_override}


def _split_party_identifier(value: str, code_len: int, account_len: int) -> Tuple[str, str, Optional[str]]:
    """Splits an optional leading Party Identifier ('/N-alpha-chars[/M-chars]')
    from the content that follows on the same line. Returns
    (party_identifier, remainder, error) — error is set when the value
    starts with '/' but doesn't decompose into valid PI subfields (e.g. the
    first subfield isn't exactly `code_len` alphabetic characters)."""
    first_line, sep, rest = value.partition("\n")
    if not first_line.startswith("/"):
        return "", value, None

    segments = first_line.split("/")
    code_segment = segments[1] if len(segments) > 1 else ""
    if not (len(code_segment) == code_len and code_segment.isalpha()):
        return "", value, (
            f"Party Identifier's first subfield must be exactly {code_len} "
            f"alphabetic character(s), got '{code_segment}' ({len(code_segment)} chars)."
        )

    if len(segments) > 2:
        account_segment = segments[2]
        if len(account_segment) > account_len:
            return "", value, (
                f"Party Identifier's second subfield must not exceed {account_len} "
                f"characters, got '{account_segment}' ({len(account_segment)} chars)."
            )
        consumed_len = 1 + len(code_segment) + 1 + len(account_segment)
    else:
        consumed_len = 1 + len(code_segment)

    party_identifier = first_line[:consumed_len]
    remainder_first_line = first_line[consumed_len:]
    remainder = (remainder_first_line + sep + rest) if remainder_first_line else rest
    return party_identifier, remainder, None


def _check_charges_currency_amount(currency: str, amount: str, amount_max_len: int) -> Optional[str]:
    """Lightweight standalone currency/amount check for
    structured_charges_or_info's per-line heuristic (see docstring below) —
    deliberately NOT sharing code with _interp_currency_amount, so nothing
    about the already-verified 32B behaviour can regress from this addition."""
    if currency not in _ISO4217_DECIMALS:
        return f"currency '{currency}' is not a recognized ISO 4217 code"
    if len(amount) > amount_max_len:
        return f"amount '{amount}' exceeds the maximum length of {amount_max_len} characters, decimal comma included"
    if "," not in amount:
        return f"amount '{amount}' is missing the mandatory decimal comma"
    integer_part, _, decimal_part = amount.partition(",")
    if not integer_part.isdigit():
        return f"amount '{amount}' must have at least one digit before the comma"
    if decimal_part and not decimal_part.isdigit():
        return f"amount '{amount}' has a non-numeric decimal part"
    allowed_decimals = _ISO4217_DECIMALS[currency]
    if len(decimal_part) > allowed_decimals:
        return f"'{decimal_part}' exceeds {currency}'s allowed precision of {allowed_decimals} decimal digit(s)"
    return None


_CCY_AMOUNT_RE = re.compile(r"^([A-Z]{3})([\d,]+)")


def _interp_structured_charges_or_info(value: str, shape: dict, tag_rules: dict) -> Optional[dict]:
    """Per-line state machine for 71D/72Z (design:
    docs/content-validator-shape-taxonomy.md). Each line is either a code
    block ('/CODE/...'), a continuation of the previous code block
    ('//...'), or free-text narrative — and once a narrative line has been
    seen, no further code or continuation line may follow (narrative must
    be the last information in the field, per 71D's usage_rules[]; applied
    to 72Z by analogy only, per the taxonomy doc's caveat).

    The currency/amount portion of a code line (71D only) is recognized
    heuristically — three uppercase letters followed by digits/commas —
    since the format brackets currency/amount and free-form "additional
    information" as independently optional with no separator; this is an
    inherent ambiguity in the SWIFT notation itself, not a parsing bug."""
    max_lines, max_line_len = shape["max_lines"], shape["max_line_len"]
    lines = value.split("\n")

    line_error = _check_lines(lines, max_lines, max_line_len)
    if line_error:
        return _violation(line_error)

    codes = {c["code"] for c in tag_rules["codes"]}
    has_ccy_amt = shape.get("has_currency_amount", False)
    ccy_params = shape.get("currency_amount_params") or {}
    amount_max_len = ccy_params.get("amount_max_len", 13)

    seen_narrative = False
    for line in lines:
        if line.startswith("//"):
            if seen_narrative:
                return _violation(f"continuation line '{line}' must not follow narrative text — narrative must be the last information in the field")
            continue

        if line.startswith("/"):
            if seen_narrative:
                return _violation(f"code line '{line}' must not follow narrative text — narrative must be the last information in the field")
            segments = line[1:].split("/", 1)
            code = segments[0]
            rest = segments[1] if len(segments) > 1 else ""
            if code not in codes:
                return _violation(f"code '{code}' is not one of the allowed codes {sorted(codes)}")
            if has_ccy_amt and rest:
                m = _CCY_AMOUNT_RE.match(rest)
                if m:
                    ccy_error = _check_charges_currency_amount(m.group(1), m.group(2), amount_max_len)
                    if ccy_error:
                        return _violation(ccy_error)
            continue

        seen_narrative = True

    return None


# --- rules[] generic rule-execution engine (STEP 1 — built, sanity-checked in
# isolation, NOT YET wired into check()'s live dispatch below) -------------
#
# Today, for the 11 tags migrated to the rules[] schema (27, 40A, 20, 31C,
# 40E, 31D, 50, 59, 32B, 41a, 49 — see docs/content-validator-shape-taxonomy.md),
# rules[] is consulted only for its error_code (_resolve_error_code); the
# _interp_* functions above still perform every actual check by reading
# shape's own embedded constraint values (shape.subfields[].constraint,
# shape.max_len, etc.) — which duplicates the same fact rules[] also states
# (e.g. tag 27's Number: shape says {"equals":"1"}, rules[27_R2] separately
# says {"min":1,"max":1}). This section is step 1 of removing that
# duplication: a generic engine that EXECUTES rules[] directly against
# already-parsed subfield values, so shape can eventually be stripped down to
# pure parsing metadata (names only) for these 11 tags. Cutting check() over
# to call this — and stripping shape — is the follow-up step; nothing below
# is called by check() yet, so none of the 142 passing tests exercise it.

def _evaluate_condition(condition: Optional[dict], subfield_values: dict) -> bool:
    """A rule's `condition` gates whether it's evaluated at all — e.g. 40E_R4
    only applies when Applicable Rules is OTHR. `condition: None` (the common
    case) always evaluates true."""
    if condition is None:
        return True
    if "exists" in condition:
        return bool(subfield_values.get(condition["exists"]))
    actual = subfield_values.get(condition["subfield"])
    if condition["operator"] == "equals":
        return actual == condition["value"]
    if condition["operator"] == "not_equals":
        return actual != condition["value"]
    raise ValueError(f"unknown condition operator {condition['operator']!r}")


def _rule_check_format(value: str, constraint: dict, subfield_name: str) -> Optional[str]:
    if constraint.get("no_slash_boundary"):
        if value.startswith("/") or value.endswith("/") or "//" in value:
            return f"value '{value}' must not start/end with '/' or contain '//'"
        return None
    if "fixed_length" in constraint:
        length = constraint["fixed_length"]
        if len(value) != length:
            return f"must be exactly {length} character(s), got '{value}' ({len(value)} chars)"
        charset = constraint.get("charset")
        if charset == "n" and not value.isdigit():
            return f"must be numeric, got '{value}'"
        if charset == "a" and not value.isalpha():
            return f"must be alphabetic, got '{value}'"
        return None
    if "max_length" in constraint:
        # Variable-length numeric (SWIFT notation without "!", e.g. "3n" = 1
        # to 3 digits) — distinct from fixed_length ("!" = exact length).
        max_length = constraint["max_length"]
        if not (1 <= len(value) <= max_length and value.isdigit()):
            return f"{subfield_name} must be 1 to {max_length} numeric digit(s), got '{value}'"
        return None
    raise ValueError(f"unrecognized format constraint {constraint!r}")


def _rule_check_numeric_range(value: str, constraint: dict, subfield_name: str) -> Optional[str]:
    if not value.isdigit():
        return f"{subfield_name} must be numeric, got '{value}'"
    lo, hi = constraint["min"], constraint["max"]
    if not (lo <= int(value) <= hi):
        if lo == hi:
            return f"{subfield_name} must have the fixed value of {lo}, got '{value}'"
        return f"{subfield_name} must be in the range {lo} to {hi}, got '{value}'"
    return None


def _rule_check_enum_membership(value: str, constraint: dict, tag_rules: dict, subfield_name: str) -> Optional[str]:
    codes = tag_rules[constraint.get("codes_ref", "codes")]
    valid = {c["code"] for c in codes}
    if value not in valid:
        listing = ", ".join(f"{c['code']} ({c['meaning']})" if c.get("meaning") else c["code"] for c in codes)
        label = "value" if subfield_name == "value" else subfield_name
        return f"{label} '{value}' is not one of the allowed codes: {listing}"
    return None


def _rule_check_max_length(value: str, constraint: dict, subfield_name: str) -> Optional[str]:
    max_len = constraint["max_len"]
    if len(value) > max_len:
        if subfield_name == "value":
            return f"value '{value}' exceeds the maximum length of {max_len} characters"
        if subfield_name == "Account":
            return f"account subfield '{value}' exceeds the maximum length of {max_len} characters"
        return f"{subfield_name} subfield '{value}' exceeds the maximum length of {max_len} characters"
    return None


def _rule_check_date_validity(value: str, constraint: dict, subfield_name: str) -> Optional[str]:
    if not _is_valid_yymmdd(value):
        if subfield_name == "value":
            return f"value '{value}' is not a valid 6!n calendar date (YYMMDD)"
        return f"{subfield_name} subfield '{value}' is not a valid 6!n calendar date"
    return None


def _rule_check_line_limit(value: str, constraint: dict) -> Optional[str]:
    return _check_lines(value.split("\n"), constraint["max_lines"], constraint["max_line_len"])


def _rule_check_forbidden(value: Optional[str], constraint: dict, subfield_name: str) -> Optional[str]:
    if value:
        label = "value" if subfield_name == "value" else f"{subfield_name} subfield"
        return f"{label} '{value}' must not be present under this condition"
    return None


def _rule_check_required(value: Optional[str], constraint: dict, subfield_name: str) -> Optional[str]:
    if not value:
        label = "a value" if subfield_name == "value" else subfield_name
        return f"{label} is required under this condition but is absent"
    return None


def _rule_check_iso4217_membership(value: str, constraint: dict) -> Optional[str]:
    if not value.isalpha() or not value.isupper():
        return f"'{value}' is not a valid {constraint.get('currency_len', 3)}!a currency code"
    if value not in _ISO4217_DECIMALS:
        return f"currency '{value}' is not a recognized ISO 4217 code"
    return None


def _rule_check_decimal_amount(value: str, constraint: dict, subfield_values: dict) -> Optional[str]:
    amount_max_len = constraint["amount_max_len"]
    if len(value) > amount_max_len:
        return f"amount '{value}' exceeds the maximum length of {amount_max_len} characters, decimal comma included"
    if "," not in value:
        return f"amount '{value}' is missing the mandatory decimal comma"
    integer_part, _, decimal_part = value.partition(",")
    if not integer_part.isdigit():
        return f"amount '{value}' must have at least one digit before the comma"
    if decimal_part and not decimal_part.isdigit():
        return f"amount '{value}' has a non-numeric decimal part"
    currency = subfield_values.get("Currency")
    if currency in _ISO4217_DECIMALS:
        allowed_decimals = _ISO4217_DECIMALS[currency]
        if len(decimal_part) > allowed_decimals:
            return f"'{decimal_part}' exceeds {currency}'s allowed precision of {allowed_decimals} decimal digit(s)"
    return None


def _rule_check_external_reference(value: str, constraint: dict) -> Optional[str]:
    """Not enforced locally — see the rule's own constraint["reference"] for
    why (no live/offline directory exists for this tag, unlike 51a's
    bic_directory_check). Exists in rules[] for spec traceability only;
    always passes, matching today's actual (shape-only) behavior."""
    return None


def _rule_check_shape_match(branch: Optional[str], constraint: dict) -> Optional[str]:
    """Fires when a bic_or_name value's parse step (_parse_bic_or_name)
    couldn't determine ANY recognized branch — the value looked like
    neither a BIC nor free-text Name/Address (nor, where applicable, a
    bare Location). `branch` is the parser's own `_branch` marker."""
    if not branch:
        return "identifier matches neither a recognized BIC shape nor a free-text Name/Address shape"
    return None


def _rule_check_bic_directory_lookup(value: str, constraint: dict) -> Optional[dict]:
    """Only used where shape["bic_directory_check"] is true (51a) — looks
    the BIC up against config/bic_directory_sample.json and returns its OWN
    specific violation (T27/T28/T29/T45/C05), since which of those five
    applies is determined dynamically by the lookup, not fixed per rule."""
    return _check_bic_directory(value)


_RULE_CHECKERS = {
    "format": lambda value, rule, sv, tr: _rule_check_format(value, rule["constraint"], rule["subfield"]),
    "numeric_range": lambda value, rule, sv, tr: _rule_check_numeric_range(value, rule["constraint"], rule["subfield"]),
    "enum_membership": lambda value, rule, sv, tr: _rule_check_enum_membership(value, rule["constraint"], tr, rule["subfield"]),
    "max_length": lambda value, rule, sv, tr: _rule_check_max_length(value, rule["constraint"], rule["subfield"]),
    "date_validity": lambda value, rule, sv, tr: _rule_check_date_validity(value, rule["constraint"], rule["subfield"]),
    "line_limit": lambda value, rule, sv, tr: _rule_check_line_limit(value, rule["constraint"]),
    "forbidden": lambda value, rule, sv, tr: _rule_check_forbidden(value, rule["constraint"], rule["subfield"]),
    "required": lambda value, rule, sv, tr: _rule_check_required(value, rule["constraint"], rule["subfield"]),
    "iso4217_membership": lambda value, rule, sv, tr: _rule_check_iso4217_membership(value, rule["constraint"]),
    "decimal_amount": lambda value, rule, sv, tr: _rule_check_decimal_amount(value, rule["constraint"], sv),
    "external_reference": lambda value, rule, sv, tr: _rule_check_external_reference(value, rule["constraint"]),
    "shape_match": lambda value, rule, sv, tr: _rule_check_shape_match(value, rule["constraint"]),
    "bic_directory_lookup": lambda value, rule, sv, tr: _rule_check_bic_directory_lookup(value, rule["constraint"]),
}


def _evaluate_rules(rules_list: List[dict], subfield_values: dict, tag_rules: dict) -> Optional[dict]:
    """Evaluates a rules[] array directly against already-parsed subfield
    values — the actual execution step rules[] has never had until now.
    Returns the FIRST failing rule's violation (matching every _interp_*
    function's "one violation per tag" behavior), or None if every
    applicable rule passes. A rule whose `condition` is false is skipped,
    not failed — e.g. 40E's Narrative rules don't fire at all when no
    Narrative was parsed out.

    A checker normally returns a plain detail string, and the violation's
    error code comes from the rule's own `error_code` — except
    bic_directory_lookup, which returns a full violation dict (detail +
    code_override) since which of T27/T28/T29/T45/C05 applies is
    determined dynamically by the lookup itself, not fixed per rule."""
    for rule in rules_list:
        if not _evaluate_condition(rule.get("condition"), subfield_values):
            continue
        value = subfield_values.get(rule["subfield"])
        if value is None and rule["rule_type"] not in ("forbidden", "required", "shape_match"):
            continue
        checker = _RULE_CHECKERS.get(rule["rule_type"])
        if checker is None:
            raise ValueError(f"unknown rule_type {rule['rule_type']!r} in rule {rule['rule_id']!r}")
        result = checker(value, rule, subfield_values, tag_rules)
        if result is None:
            continue
        if isinstance(result, dict):
            return result
        code = rule["error_code"] or ("ADVISORY" if rule["severity"] == "advisory" else None)
        return _violation(result, code_override=code)
    return None


# --- STEP 2: parsing functions, one per shape kind used by the 11 rules[]
# tags — decompose a raw value into named subfields ONLY (no constraint
# checking at all; that's _evaluate_rules's job above). Returns
# (subfield_values, structural_error) — structural_error is set only when
# the value can't even be decomposed (e.g. tag 27's separator count
# mismatch), in which case rules[] evaluation never runs, matching how
# today's _interp_* functions short-circuit on the same failure.

def _parse_text(value: str, shape: dict, tag_rules: dict) -> Tuple[dict, Optional[str]]:
    return {"value": value, "slash_boundary": value}, None


def _parse_date_yymmdd(value: str, shape: dict, tag_rules: dict) -> Tuple[dict, Optional[str]]:
    return {"value": value}, None


def _parse_enum(value: str, shape: dict, tag_rules: dict) -> Tuple[dict, Optional[str]]:
    return {"value": value}, None


def _parse_multiline(value: str, shape: dict, tag_rules: dict) -> Tuple[dict, Optional[str]]:
    body_name = shape.get("body_subfield", "value")
    prefix = shape.get("prefix")
    if not prefix:
        return {body_name: value}, None
    lines = value.split("\n")
    if lines and lines[0].startswith("/"):
        return {"Account": lines[0][1:], body_name: "\n".join(lines[1:])}, None
    return {"Account": None, body_name: value}, None


def _parse_currency_amount(value: str, shape: dict, tag_rules: dict) -> Tuple[dict, Optional[str]]:
    currency_len = shape["currency_len"]
    return {"Currency": value[:currency_len], "Amount": value[currency_len:]}, None


def _parse_conditional_narrative(value: str, shape: dict, tag_rules: dict) -> Tuple[dict, Optional[str]]:
    # Only 40E uses this kind today — subfield names are that tag's own
    # (format.subfield_labels: ["Applicable Rules", "Narrative"]), not
    # generalized, since there's nothing else to generalize against yet.
    code, _, narrative = value.partition(shape.get("separator", "/"))
    return {"Applicable Rules": code, "Narrative": narrative}, None


def _parse_composite(value: str, shape: dict, tag_rules: dict) -> Tuple[dict, Optional[str]]:
    subfields = shape["subfields"]
    if shape["layout"] == "separator":
        parts = value.split(shape["separator"])
        if len(parts) != len(subfields):
            names = "/".join(sf["name"] for sf in subfields)
            return {}, f"expected format {names} separated by '{shape['separator']}', got malformed value '{value}'"
        return {sf["name"]: part for sf, part in zip(subfields, parts)}, None
    if shape["layout"] == "positional":
        result, pos = {}, 0
        for sf in subfields:
            length, stop_at = sf.get("length"), sf.get("stop_at")
            if length is not None:
                result[sf["name"]] = value[pos:pos + length]
                pos += length
            elif stop_at is not None:
                idx = value.find(stop_at, pos)
                if idx == -1:
                    result[sf["name"]] = value[pos:]
                    pos = len(value)
                else:
                    result[sf["name"]] = value[pos:idx]
                    pos = idx + len(stop_at)
            else:
                result[sf["name"]] = value[pos:]
        return result, None
    raise ValueError(f"unknown composite layout {shape['layout']!r}")


def _parse_bic_or_name(value: str, shape: dict, tag_rules: dict) -> Tuple[dict, Optional[str]]:
    """Sets `_branch` to "A" (BIC), "D" (free text), "bare_location", or None
    (matches neither — a structural failure on its own, not tied to any one
    named subfield) — rules[] entries gate on `_branch` via `condition` to
    apply only to the branch they're relevant for."""
    pi_spec = shape.get("party_identifier", {"presence": "not_applicable"})
    result = {}
    remainder = value
    if pi_spec["presence"] != "not_applicable":
        party_identifier, remainder, pi_error = _split_party_identifier(
            remainder, pi_spec["code_subfield_len"], pi_spec["account_subfield_max_len"]
        )
        if pi_error:
            return {}, pi_error
        if party_identifier:
            segments = party_identifier.split("/")
            result["Party Identifier Code"] = segments[1] if len(segments) > 1 else ""
            result["Party Identifier Account"] = segments[2] if len(segments) > 2 else None
            result["Party Identifier"] = party_identifier

    if "trailing_code_subfield" in shape:
        lines = remainder.split("\n")
        if len(lines) < 2:
            return {}, "expected at least two lines — identifier and code"
        result["Code"] = lines[-1]
        remainder = "\n".join(lines[:-1])

    lines = remainder.split("\n")
    first_line = lines[0]
    bic_min, bic_max = shape["bic_len"]
    if len(lines) == 1 and first_line.isalnum() and len(first_line) in (bic_min, bic_max):
        result["Identifier Code"] = first_line
        result["_branch"] = "A"
        return result, None

    if "bare_location_option" in shape and len(lines) == 1:
        result["Location"] = first_line
        result["_branch"] = "bare_location"
        return result, None

    if len(lines) > 1 or " " in first_line:
        result["Name and Address"] = remainder
        result["_branch"] = "D"
        return result, None

    result["_branch"] = None
    result["Identifier Code"] = first_line
    return result, None


def _parse_structured_charges_or_info(value: str, shape: dict, tag_rules: dict) -> Tuple[dict, Optional[str]]:
    """Deliberately NOT decomposed into named subfields + rules[] like every
    other kind. This is a stateful, per-line state machine (a code/
    continuation/narrative line's validity depends on whether an earlier
    line was narrative) — it has no fixed set of independent subfields to
    check atomically, so forcing it into the rules[] model would misrepresent
    what it actually validates. 71D and 72Z both have empty
    network_validated_rules[] today (confirmed before migrating: every
    violation already shows with no bracketed code), so nothing is lost by
    treating the whole existing, unchanged _interp_structured_charges_or_info
    as this kind's "parser" — its result becomes a structural_error string,
    the same category as tag 20's slash-boundary or composite's malformed-
    separator check. rules[] is an explicit empty list for these two tags,
    not absent — that's what routes them through the new dispatch path in
    check() at all, consistent with every other migrated tag."""
    violation = _interp_structured_charges_or_info(value, shape, tag_rules)
    if violation is None:
        return {}, None
    return {}, violation["detail"]


_PARSERS = {
    "text": _parse_text,
    "enum": _parse_enum,
    "date_yymmdd": _parse_date_yymmdd,
    "multiline": _parse_multiline,
    "currency_amount": _parse_currency_amount,
    "conditional_narrative": _parse_conditional_narrative,
    "composite": _parse_composite,
    "bic_or_name": _parse_bic_or_name,
    "structured_charges_or_info": _parse_structured_charges_or_info,
}



def check(extracted_tags: List[ExtractedTag], rules: dict, logger: logging.Logger = None) -> ValidationResult:
    logger = logger or logging.getLogger(__name__)
    tags_by_number = {t["tag"]: t for t in rules["tags"]}

    errors: List[str] = []
    for t in extracted_tags:
        tag_rules = tags_by_number.get(t.canonical_tag)
        if tag_rules is None or "shape" not in tag_rules or "rules" not in tag_rules:
            continue

        if tag_rules.get("verified") is False:
            logger.warning(
                f"Tag '{t.canonical_tag}' ({tag_rules.get('field_name')}) rules are marked "
                f"unverified in rules.json — applying anyway. {tag_rules.get('verification_note', '')}"
            )

        # rules[]-schema tags (see docs/content-validator-shape-taxonomy.md):
        # shape only parses the value into named subfields; rules[] is
        # executed against them directly by _evaluate_rules.
        shape = tag_rules["shape"]
        parser = _PARSERS.get(shape["kind"])
        if parser is None:
            logger.warning(f"Tag '{t.canonical_tag}': unknown shape kind '{shape['kind']}', skipped.")
            continue
        subfield_values, structural_error = parser(t.value, shape, tag_rules)
        violation = _violation(structural_error) if structural_error else _evaluate_rules(tag_rules["rules"], subfield_values, tag_rules)
        if violation:
            code = violation["code_override"]
            suffix = f" [{code}]" if code else ""
            msg = f"Tag '{t.canonical_tag}' ({tag_rules['field_name']}): {violation['detail']}{suffix}."
            logger.error(msg)
            errors.append(msg)
        else:
            logger.debug(f"Tag '{t.canonical_tag}' content check PASSED: {t.value!r}")

    if errors:
        return ValidationResult(valid=False, errors=errors)

    logger.info("Content check PASSED — all checked tags conform to format/code/NVR rules")
    return ValidationResult(valid=True, errors=[])


def find_uncovered_tags_with_rules(rules: dict) -> List[str]:
    """Startup-time safety net: one warning per rules.json tag missing
    `shape` and/or `rules[]` — check() requires BOTH to validate a tag's
    value at all, so a tag missing either is silently never content-checked,
    regardless of whether it also happens to have codes[]. (Gating this on
    codes[] presence, as an earlier version did, stopped being a reliable
    signal once network_validated_rules[] was retired in favor of rules[] —
    the very thing being checked for.)"""
    warnings: List[str] = []
    for t in rules["tags"]:
        missing = [key for key in ("shape", "rules") if key not in t]
        if missing:
            warnings.append(
                f"Tag '{t['tag']}' ({t['field_name']}) is missing {' and '.join(repr(k) for k in missing)} "
                f"in rules.json — its value is never content-checked."
            )
    return warnings
