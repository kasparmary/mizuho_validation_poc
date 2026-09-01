"""
Expected outcomes for the TC001-TC033 validation scenarios, covering both
file structure (presence/sequence/duplicate-identifier) and field content
(format/codes/NVR on tag values) — engine.validate() runs both concerns in
one pass, so both live in a single scenario list here.

Plain Python data, deliberately NOT read from the xlsx test matrix (decision:
keep the xlsx as a separate design/review artifact, not a live test dependency,
per the explicit instruction to skip using it as runtime evidence).

Each entry: (test_id, file_name, expected_valid, expected_error_substring)
`expected_error_substring` is None for positive cases; for negative cases it's
a substring that MUST appear somewhere in the report's combined errors, so a
test can't pass for the wrong reason (e.g. failing on sequence when it was
meant to fail on presence).
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class ExpectedOutcome:
    test_id: str
    file_name: str
    scenario: str
    expected_valid: bool
    expected_error_substring: Optional[str] = None
    is_edge_case: bool = False


FILE_STRUCTURE_SCENARIOS = [
    ExpectedOutcome("TC001", "baseline_sample_header_data.txt",
                     "All 11 mandatory tags present", True),
    ExpectedOutcome("TC002", "baseline_sample_header_data.txt",
                     "Tags appear in canonical field_no order", True),
    ExpectedOutcome("TC003", "baseline_sample_header_data.txt",
                     "No tag repeats within the file", True),
    ExpectedOutcome("TC004", "missing_32B.txt",
                     "Mandatory tag 32B removed", False, "32B"),
    ExpectedOutcome("TC005", "missing_40A_and_32B.txt",
                     "Two mandatory tags removed simultaneously", False, "40A"),
    ExpectedOutcome("TC006", "swapped_20_40A.txt",
                     "20 and 40A appear out of canonical order", False, "sequence"),
    ExpectedOutcome("TC007", "duplicate_20.txt",
                     "Tag 20 appears twice", False, "duplicate"),
    ExpectedOutcome("TC008", "unknown_tag_99Z.txt",
                     "Unrecognized tag 99Z inserted", False, "not a recognized MT700 field"),
    ExpectedOutcome("TC009", "out_of_order_71D.txt",
                     "71D placed before 32B (out of canonical order)", False, "sequence"),
    ExpectedOutcome("TC010", "empty_file.txt",
                     "Completely empty input file", False, "Mandatory tag", is_edge_case=True),
    ExpectedOutcome("TC011", "mandatory_only.txt",
                     "Only mandatory tags present, all optional omitted", True, is_edge_case=True),
    ExpectedOutcome("TC012", "empty_49_value.txt",
                     "Mandatory tag 49 present but with an empty value", False, "49", is_edge_case=True),
    ExpectedOutcome("TC013", "trailing_blank_line.txt",
                     "Trailing blank line after the last tag", True, is_edge_case=True),
    ExpectedOutcome("TC014", "lowercase_41a.txt",
                     "Tag written in lowercase (41a instead of 41A)", False, "uppercase", is_edge_case=True),
    ExpectedOutcome("TC015", "baseline_sample_header_data.txt",
                     "Tag 27 baseline value from sample file", True),
    ExpectedOutcome("TC016", "tag27_number_not_one.txt",
                     "Tag 27 Number is not the fixed value 1", False, "T75"),
    ExpectedOutcome("TC017", "tag27_total_out_of_range.txt",
                     "Tag 27 Total exceeds allowed range", False, "T75", is_edge_case=True),
    ExpectedOutcome("TC018", "tag27_number_length_violation.txt",
                     "Tag 27 Number subfield exceeds fixed length", False, "27", is_edge_case=True),
    ExpectedOutcome("TC019", "baseline_sample_header_data.txt",
                     "Tag 40A baseline value from sample file", True),
    ExpectedOutcome("TC020", "tag40A_transferable.txt",
                     "Tag 40A second allowed enum value", True),
    ExpectedOutcome("TC021", "tag40A_invalid_code.txt",
                     "Tag 40A value outside the 2-code enum", False, "T60"),
    ExpectedOutcome("TC022", "tag40A_lowercase_code.txt",
                     "Tag 40A case mismatch on an otherwise valid code", False, "T60", is_edge_case=True),
    ExpectedOutcome("TC023", "baseline_sample_header_data.txt",
                     "Tag 20 baseline value from sample file", True),
    ExpectedOutcome("TC024", "tag20_leading_slash.txt",
                     "Tag 20 starts with a slash", False, "T26", is_edge_case=True),
    ExpectedOutcome("TC025", "tag20_trailing_slash.txt",
                     "Tag 20 ends with a slash", False, "T26", is_edge_case=True),
    ExpectedOutcome("TC026", "tag20_double_slash.txt",
                     "Tag 20 contains consecutive slashes", False, "T26", is_edge_case=True),
    ExpectedOutcome("TC027", "tag20_max_length_boundary.txt",
                     "Tag 20 exactly at the max-length boundary (16 chars)", True, is_edge_case=True),
    ExpectedOutcome("TC028", "tag20_exceeds_max_length.txt",
                     "Tag 20 one character past the max-length boundary (17 chars)", False, "20", is_edge_case=True),
    ExpectedOutcome("TC029", "baseline_sample_header_data.txt",
                     "Tag 31C baseline value from sample file", True),
    ExpectedOutcome("TC030", "tag31C_invalid_date.txt",
                     "Tag 31C 30-Feb does not exist on any calendar", False, "T50", is_edge_case=True),
    ExpectedOutcome("TC031", "baseline_sample_header_data.txt",
                     "Tag 40E baseline value from sample file, no narrative", True),
    ExpectedOutcome("TC032", "tag40E_narrative_on_non_othr.txt",
                     "Tag 40E narrative present on a non-OTHR code", False, "D81"),
    ExpectedOutcome("TC033", "tag40E_wrong_code.txt",
                     "Tag 40E plausible but incorrect code, confusable with a real ICC publication",
                     False, "T59", is_edge_case=True),
    ExpectedOutcome("TC034", "tag40E_narrative_exceeds_35_chars.txt",
                     "Tag 40E narrative exceeds the maximum 35-character limit", False, "exceed", is_edge_case=True),
    ExpectedOutcome("TC035", "tag40E_empty_narrative.txt",
                     "Tag 40E OTHR code has an empty narrative", False, "ADVISORY", is_edge_case=True),
    ExpectedOutcome("TC036", "tag40E_missing_narrative.txt",
                     "Tag 40E OTHR code has no narrative", False, "ADVISORY", is_edge_case=True),

    # TC037-TC048: tags 42C, 42a, 44C, 44D (Drafts at.../Drawee/Latest Date of
    # Shipment/Shipment Period). C1/C2/C3 cross-field presence rules are out of
    # scope for content_validator.py (see its module docstring) — these cases
    # exercise only each tag's own format/NVR/usage-rule check in isolation.
    ExpectedOutcome("TC037", "baseline_sample_header_data.txt",
                     "Tag 44C baseline value from sample file", True),
    ExpectedOutcome("TC038", "baseline_with_42C_and_42a.txt",
                     "Tag 42C valid narrative present", True),
    ExpectedOutcome("TC039", "baseline_with_42C_and_42a.txt",
                     "Tag 42a Option A (BIC) value present", True),
    ExpectedOutcome("TC040", "tag42a_free_text_option_d.txt",
                     "Tag 42a Option D (free-text Name and Address) accepted", True),
    ExpectedOutcome("TC041", "baseline_with_44D_field.txt",
                     "Tag 44D valid narrative present", True),
    ExpectedOutcome("TC042", "tag42C_exceeds_35_chars.txt",
                     "Tag 42C narrative line exceeds the 35-character limit", False, "exceed", is_edge_case=True),
    ExpectedOutcome("TC043", "tag42C_exceeds_3_lines.txt",
                     "Tag 42C narrative exceeds the 3-line maximum", False, "exceed", is_edge_case=True),
    ExpectedOutcome("TC044", "tag42a_party_identifier_present.txt",
                     "Tag 42a Party Identifier subfield present (forbidden by usage rule)", False,
                     "Party Identifier", is_edge_case=True),
    ExpectedOutcome("TC045", "tag42a_invalid_shape.txt",
                     "Tag 42a value matches neither BIC nor free-text shape", False, "T27"),
    ExpectedOutcome("TC046", "tag44C_invalid_date.txt",
                     "Tag 44C 30-Feb does not exist on any calendar", False, "T50"),
    ExpectedOutcome("TC047", "tag44D_exceeds_65_chars.txt",
                     "Tag 44D narrative line exceeds the 65-character limit", False, "exceed", is_edge_case=True),
    ExpectedOutcome("TC048", "tag44D_exceeds_6_lines.txt",
                     "Tag 44D narrative exceeds the 6-line maximum", False, "exceed", is_edge_case=True),

    # TC049-TC056: tag 51a (Applicant Bank). Same Option A/D shape as 42a, but
    # WITHOUT 42a's "Party Identifier must not be present" restriction — 51a's
    # rules.json usage_rules is empty, so a Party Identifier prefix is allowed
    # here (TC053 proves this differs from 42a's TC044).
    ExpectedOutcome("TC049", "tag51a_bic_8char.txt",
                     "Tag 51a Option A (BIC) value, 8 characters", True),
    ExpectedOutcome("TC050", "tag51a_bic_11char.txt",
                     "Tag 51a Option A (BIC) value with branch code, 11 characters", True, is_edge_case=True),
    ExpectedOutcome("TC051", "tag51a_free_text_multiline.txt",
                     "Tag 51a Option D (free-text Name and Address), multi-line", True),
    ExpectedOutcome("TC052", "tag51a_free_text_single_line.txt",
                     "Tag 51a Option D free text on a single line (no address lines)", True, is_edge_case=True),
    ExpectedOutcome("TC053", "tag51a_party_identifier_present.txt",
                     "Tag 51a Party Identifier subfield present (allowed, unlike 42a)", True, is_edge_case=True),
    ExpectedOutcome("TC054", "tag51a_invalid_shape.txt",
                     "Tag 51a value matches neither BIC nor free-text shape", False, "T27"),
    ExpectedOutcome("TC055", "tag51a_exceeds_4_lines.txt",
                     "Tag 51a Option D narrative exceeds the 4-line maximum", False, "exceed", is_edge_case=True),
    ExpectedOutcome("TC056", "tag51a_line_exceeds_35_chars.txt",
                     "Tag 51a single line exceeds the 35-character limit", False, "exceed", is_edge_case=True),

    # TC057-TC060: message-level cross-field rules C1/C2/C3
    # (rules.json's message_level_network_validated_rules), enforced by
    # src/validators/cross_field_validator.py — a separate pipeline stage
    # from content_validator.py since these compare DIFFERENT tags against
    # each other rather than checking one tag's own value.
    ExpectedOutcome("TC057", "tag42C_missing_42a_partner.txt",
                     "Rule C1 violated: 42C present without its required 42a partner", False, "C1"),
    ExpectedOutcome("TC058", "tag42_group_and_42M_together.txt",
                     "Rule C2 violated: 42C+42a group present together with 42M", False, "C2"),
    ExpectedOutcome("TC059", "tag44C_and_44D_together.txt",
                     "Rule C3 violated: 44C and 44D both present", False, "C3"),
    ExpectedOutcome("TC060", "tag42M_alone.txt",
                     "Rule C2 satisfied: 42M present alone (its own group, no conflict)", True),

    # TC061-TC076: tags 42M, 42P (4*35x narrative, same pattern as 42C), and
    # 58a/53a/57a (BIC-or-Name/Address, same pattern as 42a/51a). 57a has an
    # extra Option B "bare Location" branch (_check_57a) the others don't.
    ExpectedOutcome("TC061", "tag42M_valid.txt",
                     "Tag 42M valid narrative", True),
    ExpectedOutcome("TC062", "tag42M_exceeds_35_chars.txt",
                     "Tag 42M line exceeds the 35-character limit", False, "exceed", is_edge_case=True),
    ExpectedOutcome("TC063", "tag42M_exceeds_4_lines.txt",
                     "Tag 42M exceeds the 4-line maximum", False, "exceed", is_edge_case=True),
    ExpectedOutcome("TC064", "tag42P_valid.txt",
                     "Tag 42P valid narrative", True),
    ExpectedOutcome("TC065", "tag42P_exceeds_35_chars.txt",
                     "Tag 42P line exceeds the 35-character limit", False, "exceed", is_edge_case=True),
    ExpectedOutcome("TC066", "tag42P_exceeds_4_lines.txt",
                     "Tag 42P exceeds the 4-line maximum", False, "exceed", is_edge_case=True),
    ExpectedOutcome("TC067", "tag58a_bic.txt",
                     "Tag 58a Option A (BIC) value", True),
    ExpectedOutcome("TC068", "tag58a_invalid_shape.txt",
                     "Tag 58a value matches neither BIC nor free-text shape", False, "T27"),
    ExpectedOutcome("TC069", "tag53a_bic.txt",
                     "Tag 53a Option A (BIC) value", True),
    ExpectedOutcome("TC070", "tag53a_invalid_shape.txt",
                     "Tag 53a value matches neither BIC nor free-text shape", False, "T27"),
    ExpectedOutcome("TC071", "tag57a_bic.txt",
                     "Tag 57a Option A (BIC) value", True),
    ExpectedOutcome("TC072", "tag57a_location_option_b.txt",
                     "Tag 57a Option B bare Location value (no space, not BIC-shaped)", True, is_edge_case=True),
    ExpectedOutcome("TC073", "tag57a_free_text_option_d.txt",
                     "Tag 57a Option D (free-text Name and Address), multi-line", True),
    ExpectedOutcome("TC074", "tag57a_line_exceeds_35_chars.txt",
                     "Tag 57a single line exceeds the 35-character limit", False, "exceed", is_edge_case=True),
    ExpectedOutcome("TC075", "tag57a_exceeds_4_lines.txt",
                     "Tag 57a exceeds the 4-line maximum", False, "exceed", is_edge_case=True),
    ExpectedOutcome("TC076", "tag57a_party_identifier_present.txt",
                     "Tag 57a Party Identifier subfield present (allowed, like 51a/58a/53a)", True, is_edge_case=True),
]
