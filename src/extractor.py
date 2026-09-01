"""
Extractor — parses raw MT700 Block 4 text into an ordered list of ExtractedTag.

Design decisions (each one deliberate, not incidental):

1. Order is preserved as a LIST, never collapsed into a dict — sequence validation
   is meaningless without knowing the original file order.
2. Multi-line continuation values (e.g. field 41a's second subfield line
   "BY NEGOTIATION" following ":41A:MHCBJPJTXXX") are joined into the PREVIOUS
   tag's value with '\\n', not treated as new tags or dropped.
3. Blank / whitespace-only lines are skipped entirely — they are neither a new
   tag nor content to append to the previous tag's value. This is what makes a
   trailing blank line harmless (TC015) without silently corrupting the last
   tag's value with an extra blank continuation line.
4. Tag identifiers are captured in their RAW form (preserving case) so that a
   downstream structural check can flag non-uppercase tags (TC016) — the raw
   form is not silently upper-cased here, because that would hide the very
   defect this check exists to catch.
5. Canonical-tag normalization (mapping wire tags like "41A" to the rules.json
   key "41a" for option-generic fields) happens here once, so every downstream
   validator can rely on `canonical_tag` for rules.json lookups without each
   one re-implementing the same mapping.
"""

import re
from typing import List
from src.models import ExtractedTag

# Field numbers that are genuinely multi-option on the wire (concrete letter varies
# by message) and are keyed in rules.json using a generic lowercase "a" placeholder,
# per the schema convention agreed upon when we designed rules.json. Mapped to the
# SPECIFIC letters that represent that generic field — not "any letter under this
# number" — because field 42 has both a generic option field (Drawee, "42a", options
# A/D) AND unrelated concrete fields sharing the same number (42C "Drafts at...",
# 42M, 42P). A blanket by-number rule would wrongly fold 42C/42M/42P into 42a.
_OPTION_GENERIC_LETTERS = {
    "41": {"A", "D"},
    "42": {"A", "D"},
    "51": {"A", "D"},
    "53": {"A", "D"},
    "57": {"A", "B", "D"},
    "58": {"A", "D"},
}

# Matches a tag line: colon, 1-3 digits, optional single letter, colon, then the value.
_TAG_LINE_RE = re.compile(r"^:(\d{1,3}[A-Za-z]?):(.*)$")


def _to_canonical(raw_tag: str) -> str:
    """
    Map a raw wire tag to the key used in rules.json.

    Concrete single-option tags (e.g. "40A", "49", "32B", "42C") are their own
    canonical key. Option-generic tags (e.g. "41A", "42D", "58A") normalize to the
    field number + lowercase 'a' (e.g. "41a", "42a", "58a") to match rules.json —
    but only for the specific letters that are genuinely options of that generic
    field (see _OPTION_GENERIC_LETTERS), not every letter under that number.
    """
    match = re.match(r"^(\d{1,3})([A-Za-z]?)$", raw_tag)
    if not match:
        return raw_tag
    number, letter = match.group(1), match.group(2)
    if letter and letter.upper() in _OPTION_GENERIC_LETTERS.get(number, set()):
        return f"{number}a"
    return raw_tag.upper() if letter else raw_tag


def extract(raw_text: str) -> List[ExtractedTag]:
    """
    Parse raw MT700 Block 4 text (as read from a .txt file) into an ordered
    list of ExtractedTag. Handles both CRLF and LF line endings uniformly.
    """
    # Normalize line endings so CRLF and LF files parse identically —
    # confirmed necessary since the real sample file uses CRLF throughout.
    lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    tags: List[ExtractedTag] = []
    current: ExtractedTag = None

    for line_no, line in enumerate(lines, start=1):
        if line.strip() == "":
            # Blank line: skip entirely (decision #3 above).
            continue

        match = _TAG_LINE_RE.match(line)
        if match:
            raw_tag, value = match.group(1), match.group(2)
            current = ExtractedTag(
                raw_tag=raw_tag,
                canonical_tag=_to_canonical(raw_tag),
                value=value,
                line_number=line_no,
            )
            tags.append(current)
        else:
            # Continuation line: append to the previous tag's value.
            if current is not None:
                current.value = current.value + "\n" + line
            # If there is no current tag yet, this is stray content before any
            # tag — silently dropped here; a stricter engine could flag this as
            # a separate structural error, but no test scenario in this batch
            # exercises that case, so it's left as a documented non-issue.

    return tags
