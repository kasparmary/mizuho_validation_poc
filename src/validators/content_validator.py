"""
Content validator — confirms a tag's VALUE conforms to its format, code list,
and network-validated rules (NVR) from rules.json, as opposed to the file-
structure validators (presence/sequence/tag identifier) which only ever look at
tag identifiers, never the values inside them.

Covers tags 27, 40A, 20, 31C, 40E, 31D, 50, 59, 32B, 41a, 49, 42C, 42a, 42M,
42P, 44C, 44D, 51a, 58a, 53a, 57a.
Each tag gets its own check function rather than a generic rule interpreter,
because each one's rule shape is genuinely different (subfield split + fixed
value + range, vs. enum, vs. slash rules + max length, vs. calendar-date
validity, vs. enum + conditional narrative, vs. multi-line length limits).
Extending to another tag means adding one more function and one more
dispatch entry, not reworking a one-size-fits-all interpreter.

Deliberately OUT OF SCOPE (single-tag checks can't express this — it compares
two DIFFERENT tags against each other, a cross-field concern, not a content
concern):
  - Usage Rule: 58a should be present when 49 is MAY ADD or CONFIRM.
This would need the same treatment as C1/C2/C3 below.

C1 (42C/42a co-presence), C2 (42C+42a / 42M / 42P mutual exclusion), and C3
(44C/44D mutual exclusion) are NOT handled here — they're message-level rules
that need the full extracted_tags list at once, not a per-tag value check.
See src/validators/cross_field_validator.py, which evaluates rules.json's
`message_level_network_validated_rules` generically.

NOT YET BUILT — extending to a second SWIFT message type (e.g. MT730): most
tag numbers are reused across message types with identical rules, so the
`_CHECKS` dict below should stay the default/shared case. Only where a tag's
rule genuinely differs by message type would this need an override layer,
e.g.:

    _CHECKS_OVERRIDES = {"MT730": {"20": _check_20_mt730}}

    def _get_check_fn(canonical_tag, message_type):
        return _CHECKS_OVERRIDES.get(message_type, {}).get(canonical_tag) \
            or _CHECKS.get(canonical_tag)

`rules.json` already carries `message_type` at the top level, so `check()`'s
external signature (`check(extracted_tags, rules, logger)`) would not need
to change to support this — only this module's internals would. Existing
`_check_*()` functions and the shared `_CHECKS` table stay untouched for
every tag whose rule doesn't actually diverge.
"""

import logging
import re
from datetime import date
from typing import List, Optional, Tuple
from src.models import ExtractedTag, ValidationResult

_40A_CODES = {"IRREVOCABLE", "IRREVOCABLE TRANSFERABLE"}
_40E_CODES = {
    "UCP LATEST VERSION",
    "UCPURR LATEST VERSION",
    "EUCP LATEST VERSION",
    "EUCPURR LATEST VERSION",
    "OTHR",
}
_41A_CODES = {"BY ACCEPTANCE", "BY DEF PAYMENT", "BY MIXED PYMT", "BY NEGOTIATION", "BY PAYMENT"}
_49_CODES = {"CONFIRM", "MAY ADD", "WITHOUT"}

# ISO 4217 minor-unit (decimal) precision, for the currencies exercised so far.
# Not the full ISO 4217 list — extend as new currencies show up in test data.
_ISO4217_DECIMALS = {
    "USD": 2, "EUR": 2, "GBP": 2, "JPY": 0, "KRW": 0, "CNY": 2, "CHF": 2,
    "AUD": 2, "CAD": 2, "SGD": 2, "HKD": 2, "INR": 2, "THB": 2, "AED": 2,
    "BHD": 3, "KWD": 3, "OMR": 3,
}


def _is_valid_yymmdd(date_str: str) -> bool:
    """6!n date validity shared by 31C, 31D's date subfield, and 44C."""
    if not (len(date_str) == 6 and date_str.isdigit()):
        return False
    yy, mm, dd = int(date_str[0:2]), int(date_str[2:4]), int(date_str[4:6])
    try:
        date(2000 + yy, mm, dd)
        return True
    except ValueError:
        return False


def _check_multiline(value: str, max_lines: int, max_line_len: int) -> Optional[str]:
    """Shared N*Mx narrative-field shape check (line count + per-line length)."""
    lines = value.split("\n")
    if len(lines) > max_lines:
        return f"exceeds the {max_lines}-line maximum ({max_lines}*{max_line_len}x)"
    for line in lines:
        if len(line) > max_line_len:
            return f"line '{line}' exceeds {max_line_len} characters ({max_lines}*{max_line_len}x)"
    return None


def _check_27(value: str) -> Optional[str]:
    parts = value.split("/")
    if len(parts) != 2:
        return "Tag '27': expected format '1!n/1!n' (Number/Total), got malformed value."

    number, total = parts
    if not (len(number) == 1 and number.isdigit()) or not (len(total) == 1 and total.isdigit()):
        return f"Tag '27': value '{value}' violates format 1!n/1!n (each subfield must be exactly one digit)."

    if number != "1":
        return f"Tag '27': Number must have the fixed value of 1, got '{number}' [T75]."

    if not (1 <= int(total) <= 8):
        return f"Tag '27': Total must be in the range 1 to 8, got '{total}' [T75]."

    return None


def _check_40A(value: str) -> Optional[str]:
    if value not in _40A_CODES:
        return f"Tag '40A': value '{value}' is not one of the allowed codes {sorted(_40A_CODES)} [T60]."
    return None


def _check_20(value: str) -> Optional[str]:
    if value.startswith("/") or value.endswith("/") or "//" in value:
        return f"Tag '20': value '{value}' must not start/end with '/' or contain '//' [T26]."
    if len(value) > 16:
        return f"Tag '20': value '{value}' exceeds the maximum length of 16 characters."
    return None


def _check_31C(value: str) -> Optional[str]:
    if not _is_valid_yymmdd(value):
        return f"Tag '31C': value '{value}' is not a valid 6!n calendar date (YYMMDD) [T50]."
    return None


def _check_40E(value: str) -> Optional[str]:
    code, _, narrative = value.partition("/")
    if code not in _40E_CODES:
        return f"Tag '40E': code '{code}' is not one of the allowed codes {sorted(_40E_CODES)} [T59]."
    if narrative and code != "OTHR":
        return f"Tag '40E': narrative is only allowed when the code is OTHR, got code '{code}' with narrative [D81]."
    if code == "OTHR" and not narrative.strip():
        return f"Tag '40E': narrative must be provided when code is OTHR [ADVISORY]."
    if narrative and len(narrative) > 35:
        return f"Tag '40E': narrative must not exceed 35 characters, got {len(narrative)} characters."
    return None


def _check_31D(value: str) -> Optional[str]:
    date_part, place = value[:6], value[6:]
    if not _is_valid_yymmdd(date_part):
        return f"Tag '31D': date subfield '{date_part}' is not a valid 6!n calendar date [T50]."
    if not place:
        return "Tag '31D': Place subfield is mandatory and must not be empty."
    if len(place) > 29:
        return f"Tag '31D': Place subfield '{place}' exceeds the maximum length of 29 characters."
    return None


def _check_50(value: str) -> Optional[str]:
    error = _check_multiline(value, max_lines=4, max_line_len=35)
    return f"Tag '50': {error}." if error else None


def _check_59(value: str) -> Optional[str]:
    lines = value.split("\n")
    if lines and lines[0].startswith("/"):
        account, name_lines = lines[0][1:], lines[1:]
        if len(account) > 34:
            return f"Tag '59': account subfield '{account}' exceeds the maximum length of 34 characters."
    else:
        name_lines = lines

    error = _check_multiline("\n".join(name_lines), max_lines=4, max_line_len=35)
    return f"Tag '59': {error}." if error else None


def _check_32B(value: str) -> Optional[str]:
    currency, amount = value[:3], value[3:]
    if not currency.isalpha() or not currency.isupper():
        return f"Tag '32B': '{currency}' is not a valid 3!a currency code [T52]."
    if currency not in _ISO4217_DECIMALS:
        return f"Tag '32B': currency '{currency}' is not a recognized ISO 4217 code [T52]."

    if "," not in amount:
        return f"Tag '32B': amount '{amount}' is missing the mandatory decimal comma [C03/T40]."
    integer_part, _, decimal_part = amount.partition(",")
    if not integer_part.isdigit():
        return f"Tag '32B': amount '{amount}' must have at least one digit before the comma [T40]."
    if decimal_part and not decimal_part.isdigit():
        return f"Tag '32B': amount '{amount}' has a non-numeric decimal part."

    allowed_decimals = _ISO4217_DECIMALS[currency]
    if len(decimal_part) > allowed_decimals:
        return (
            f"Tag '32B': '{decimal_part}' exceeds {currency}'s allowed precision "
            f"of {allowed_decimals} decimal digit(s) [T43]."
        )
    return None


def _check_41a(value: str) -> Optional[str]:
    lines = value.split("\n")
    if len(lines) != 2:
        return "Tag '41a': expected two lines — identifier and code."

    identifier, code = lines
    is_bic_shape = identifier.isalnum() and len(identifier) in (8, 11)
    is_free_text_shape = " " in identifier
    if not is_bic_shape and not is_free_text_shape:
        return (
            f"Tag '41a': identifier '{identifier}' matches neither a BIC shape "
            f"(8 or 11 alphanumeric chars) nor Option D free-text shape [T27/T28/T29/T45/C05]."
        )

    if code not in _41A_CODES:
        return f"Tag '41a': code '{code}' is not one of the allowed codes {sorted(_41A_CODES)} [T68]."
    return None


# Optional leading Party Identifier ("[/1!a][/34x]") shared by 42a/51a's
# Option A/D format — one or two slash-delimited subfields on the first line,
# before the real BIC/Name-and-Address content begins.
_PARTY_IDENTIFIER_PREFIX = re.compile(r"^(/[^/\n]{0,34}){1,2}")


def _split_party_identifier(value: str) -> Tuple[str, str]:
    first_line, sep, rest = value.partition("\n")
    match = _PARTY_IDENTIFIER_PREFIX.match(first_line)
    if not match:
        return "", value
    party_identifier = match.group(0)
    remainder = first_line[match.end():]
    return party_identifier, remainder + sep + rest


def _check_bic_or_name_option(core_value: str, tag_label: str) -> Optional[str]:
    """Shared Option A (BIC) / Option D (free-text Name and Address) shape
    check for 42a/51a — same BIC-shape heuristic as 41a, minus 41a's extra
    trailing Code line (42a/51a have no code subfield, just the identity)."""
    lines = core_value.split("\n")
    first_line = lines[0]
    is_bic_shape = len(lines) == 1 and first_line.isalnum() and len(first_line) in (8, 11)
    if is_bic_shape:
        return None

    is_free_text_shape = len(lines) > 1 or " " in first_line
    if not is_free_text_shape:
        return (
            f"Tag '{tag_label}': identifier '{first_line}' matches neither a BIC shape "
            f"(8 or 11 alphanumeric chars) nor Option D free-text shape [T27/T28/T29/T45/C05]."
        )

    error = _check_multiline(core_value, max_lines=4, max_line_len=35)
    return f"Tag '{tag_label}': {error}." if error else None


def _check_42a(value: str) -> Optional[str]:
    party_identifier, remainder = _split_party_identifier(value)
    if party_identifier:
        return (
            f"Tag '42a': Party Identifier subfield '{party_identifier}' must not be "
            f"present, per usage rule."
        )
    return _check_bic_or_name_option(remainder, "42a")


def _check_51a(value: str) -> Optional[str]:
    _, remainder = _split_party_identifier(value)
    return _check_bic_or_name_option(remainder, "51a")


def _check_49(value: str) -> Optional[str]:
    if value not in _49_CODES:
        return f"Tag '49': value '{value}' is not one of the allowed codes {sorted(_49_CODES)} [T67]."
    return None


def _check_42C(value: str) -> Optional[str]:
    error = _check_multiline(value, max_lines=3, max_line_len=35)
    return f"Tag '42C': {error}." if error else None


def _check_42M(value: str) -> Optional[str]:
    error = _check_multiline(value, max_lines=4, max_line_len=35)
    return f"Tag '42M': {error}." if error else None


def _check_42P(value: str) -> Optional[str]:
    error = _check_multiline(value, max_lines=4, max_line_len=35)
    return f"Tag '42P': {error}." if error else None


def _check_58a(value: str) -> Optional[str]:
    _, remainder = _split_party_identifier(value)
    return _check_bic_or_name_option(remainder, "58a")


def _check_53a(value: str) -> Optional[str]:
    _, remainder = _split_party_identifier(value)
    return _check_bic_or_name_option(remainder, "53a")


def _check_57a(value: str) -> Optional[str]:
    """57a has a 3rd format option 42a/51a/58a/53a don't: Option B, a bare
    Location field ('[/1!a][/34x] [35x]', no address-block structure). Since
    Option B and Option D share the same 35-char per-line cap, a single-line
    value under that cap is valid either way regardless of whether it looks
    like a BIC-shape-mismatch (e.g. a bare city name with no space) — unlike
    _check_bic_or_name_option, this does NOT reject a spaceless single line
    as 'neither shape'."""
    _, remainder = _split_party_identifier(value)
    lines = remainder.split("\n")
    first_line = lines[0]

    is_bic_shape = len(lines) == 1 and first_line.isalnum() and len(first_line) in (8, 11)
    if is_bic_shape:
        return None

    if len(lines) == 1:
        if len(first_line) > 35:
            return f"Tag '57a': value '{first_line}' exceeds the maximum length of 35 characters."
        return None

    error = _check_multiline(remainder, max_lines=4, max_line_len=35)
    return f"Tag '57a': {error}." if error else None


def _check_44C(value: str) -> Optional[str]:
    if not _is_valid_yymmdd(value):
        return f"Tag '44C': value '{value}' is not a valid 6!n calendar date (YYMMDD) [T50]."
    return None


def _check_44D(value: str) -> Optional[str]:
    error = _check_multiline(value, max_lines=6, max_line_len=65)
    return f"Tag '44D': {error}." if error else None


_CHECKS = {
    "27": _check_27,
    "40A": _check_40A,
    "20": _check_20,
    "31C": _check_31C,
    "40E": _check_40E,
    "31D": _check_31D,
    "50": _check_50,
    "59": _check_59,
    "32B": _check_32B,
    "41a": _check_41a,
    "49": _check_49,
    "42C": _check_42C,
    "42a": _check_42a,
    "42M": _check_42M,
    "42P": _check_42P,
    "44C": _check_44C,
    "44D": _check_44D,
    "51a": _check_51a,
    "58a": _check_58a,
    "53a": _check_53a,
    "57a": _check_57a,
}


def check(extracted_tags: List[ExtractedTag], rules: dict, logger: logging.Logger = None) -> ValidationResult:
    logger = logger or logging.getLogger(__name__)

    errors: List[str] = []
    for t in extracted_tags:
        check_fn = _CHECKS.get(t.canonical_tag)
        if check_fn is None:
            continue

        error = check_fn(t.value)
        if error:
            logger.error(error)
            errors.append(error)
        else:
            logger.debug(f"Tag '{t.canonical_tag}' content check PASSED: {t.value!r}")

    if errors:
        return ValidationResult(valid=False, errors=errors)

    logger.info("Content check PASSED — all checked tags conform to format/code/NVR rules")
    return ValidationResult(valid=True, errors=[])
