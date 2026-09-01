"""
Core data models for the MT700 validation engine.

Every validator returns a ValidationResult (never a bare bool/string mix) so that
callers always get a validity flag AND a list of human-readable reasons, even when
there's exactly zero or one reason. This mirrors the same pattern used throughout
the earlier tag-content validators (mt700_validator.py) for consistency.
"""

from dataclasses import dataclass, field
from typing import List, Tuple


@dataclass
class ValidationResult:
    """Result of a single validation stage (presence / sequence / tag identifier)."""
    valid: bool
    errors: List[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.valid


@dataclass
class ExtractedTag:
    """One tag as parsed from the raw file, preserving both raw and canonical form."""
    raw_tag: str          # exactly as it appeared on the wire, e.g. "41A" or "41a"
    canonical_tag: str     # normalized form used to look up rules.json, e.g. "41a"
    value: str              # the tag's value, multi-line continuations joined with '\n'
    line_number: int        # 1-indexed line where this tag started, for diagnostics


@dataclass
class ValidationReport:
    """Full result of running the validation pipeline against one input file."""
    file_name: str
    extracted_tags: List[ExtractedTag]
    presence_result: ValidationResult
    sequence_result: ValidationResult
    tag_identifier_result: ValidationResult
    content_result: ValidationResult
    cross_field_result: ValidationResult

    @property
    def overall_valid(self) -> bool:
        return (
            self.presence_result.valid
            and self.sequence_result.valid
            and self.tag_identifier_result.valid
            and self.content_result.valid
            and self.cross_field_result.valid
        )

    def all_errors(self) -> List[str]:
        return (
            self.presence_result.errors
            + self.sequence_result.errors
            + self.tag_identifier_result.errors
            + self.content_result.errors
            + self.cross_field_result.errors
        )

    def tag_summary(self) -> List[Tuple[str, str]]:
        """(raw_tag, value) pairs in file order — useful for evidence attachments."""
        return [(t.raw_tag, t.value) for t in self.extracted_tags]
