# MT700 Validation POC

Validates an MT700 input file (Documentary Credit issuance message, Block 4)
against the SWIFT Category 7 Message Reference Guide, across three concerns:

- **File structure** — presence of mandatory tags, correct tag sequence (per
  the guide's field `No.` order), and tag-identifier legitimacy (no
  duplicates, no unrecognized tags, uppercase wire format).
- **Field content** — tag *values* checked against format, code lists, and
  network-validated rules (NVR) from `config/rules.json`, for 21 of the 39
  MT700 tags (see "Content Validation Coverage — Tag by Tag" below for the
  full breakdown).
- **Cross-field rules** — message-level rules that compare DIFFERENT tags
  against each other (SWIFT's C1/C2/C3: 42C/42a co-presence, 42-group vs 42M
  vs 42P mutual exclusion, 44C/44D mutual exclusion), driven generically by
  `rules.json`'s `message_level_network_validated_rules` array.

Covers **76 scenarios (TC001–TC076)** in `utils/expected_results.py`. The
first ~33 trace back to the original MT700 test matrix
(`docs/MT700_Test_Scenarios_sample_header_data.xlsx`); everything from
TC034 onward was added since, extending coverage tag by tag and rule by rule
— that file's docstring and inline comments are the authoritative source for
what each scenario covers, not this README.

## Content Validation Coverage — Tag by Tag

21 of the 39 MT700 tags have field-content validation (format, code list,
and network-validated-rule checks on the tag's *value*). All tags —
covered or not — still get file-structure checks (presence if Mandatory,
canonical sequence, no duplicates, no unrecognized tags, uppercase
convention) via the earlier pipeline stages; the distinction below is only
about the deeper *value-level* check in `content_validator.py`.

**Covered (21):**

| Tag | Field Name |
|---|---|
| 27 | Sequence of Total |
| 40A | Form of Documentary Credit |
| 20 | Documentary Credit Number |
| 31C | Date of Issue |
| 40E | Applicable Rules |
| 31D | Date and Place of Expiry |
| 51a | Applicant Bank |
| 50 | Applicant |
| 59 | Beneficiary |
| 32B | Currency Code, Amount |
| 41a | Available With ... By ... |
| 42C | Drafts at ... |
| 42a | Drawee |
| 42M | Mixed Payment Details |
| 42P | Negotiation/Deferred Payment Details |
| 44C | Latest Date of Shipment |
| 44D | Shipment Period |
| 49 | Confirmation Instructions |
| 58a | Requested Confirmation Party |
| 53a | Reimbursing Bank |
| 57a | 'Advise Through' Bank |

**Not yet covered (18):**

| Tag | Field Name |
|---|---|
| 23 | Reference to Pre-Advice |
| 39A | Percentage Credit Amount Tolerance |
| 39C | Additional Amounts Covered |
| 43P | Partial Shipments |
| 43T | Transhipment |
| 44A | Place of Taking in Charge/Dispatch from .../Place of Receipt |
| 44E | Port of Loading/Airport of Departure |
| 44F | Port of Discharge/Airport of Destination |
| 44B | Place of Final Destination/For Transportation to .../Place of Delivery |
| 45A | Description of Goods and/or Services |
| 46A | Documents Required |
| 47A | Additional Conditions |
| 49G | Special Payment Conditions for Beneficiary |
| 49H | Special Payment Conditions for Bank Only |
| 71D | Charges |
| 48 | Period for Presentation in Days |
| 78 | Instructions to the Paying/Accepting/Negotiating Bank |
| 72Z | Sender to Receiver Information |

Extending coverage to any of the above means adding one check function plus
its `_CHECKS` dispatch entry in `content_validator.py` — no other pipeline
stage changes. `.claude/skills/mt700-tag-validation/` has the step-by-step
procedure, including which shapes already have a reusable helper (calendar
date, multiline narrative, BIC-or-Name/Address).

## Setup

```bash
pip install -r requirements.txt
```

Generating the HTML report additionally requires the Allure command-line tool
(separate from `allure-pytest`, which only writes raw results):

```bash
npm install -g allure-commandline --save-dev
# or: brew install allure  /  apt-get install allure  (platform-dependent)
```

## Running

```powershell
.\run_tests.ps1
```

This runs `pytest` (which wipes and rewrites `reports/allure-results/` fresh
on every run, via `--clean-alluredir`) and then always regenerates
`reports/allure-report/` from those results — so the HTML report can never go
stale or drift from the last test run.

Equivalent manual steps, if you need them:

```bash
pytest
allure generate reports/allure-results -o reports/allure-report --clean
allure open reports/allure-report
```

## What each test's Allure report entry contains

- **Issues Found (missing/invalid items only)** — WARNING/ERROR-level log
  records only (INFO/DEBUG "everything passed" noise is filtered out), also
  written to `reports/logs/<test_id>.log` as a standalone file.
- **Raw Input** — the exact `.txt` fixture fed to the engine, unmodified —
  lets you compare the original SWIFT message text against the result.
- **Validation Report** — the structured pass/fail + error list for each of
  the five pipeline stages (presence, tag identifier, sequence, content,
  cross-field).

Tests are grouped in the report's **Behaviors** tab (not just Suites) into
Positive Cases / Negative Cases / Edge Cases, based on each scenario's
`expected_valid` and `is_edge_case` fields in `expected_results.py`.

## Pipeline

```
raw file text
    -> extractor.extract()          ordered list of (tag, value), CRLF/LF-safe,
                                     multi-line continuations joined correctly
    -> presence_validator.check()       all Mandatory tags present & non-empty?
    -> tag_identifier_validator.check() no repeats, no unknown tags, uppercase identifiers?
    -> sequence_validator.check()       present (recognized) tags in canonical field_no order?
    -> content_validator.check()        tag values conform to format/codes/NVR rules?
    -> cross_field_validator.check()    message-level rules across DIFFERENT tags (SWIFT's C1/C2/C3)?
```

All five validators always run (not short-circuited), so a single test run
surfaces every problem in a file at once, not just the first one encountered.
Tag identifier check runs before sequence deliberately, so an unrecognized
tag is diagnosed clearly there first rather than also showing up as a
confusing "out of sequence" error.

## Project layout

```
src/
  extractor.py                    Parses raw Block 4 text into ordered ExtractedTag list
  engine.py                       Orchestrates the pipeline, returns ValidationReport
  models.py                       ValidationResult / ExtractedTag / ValidationReport dataclasses
  validators/
    presence_validator.py         Stage 1
    tag_identifier_validator.py   Stage 2 (duplicates / unknown tags / uppercase convention)
    sequence_validator.py         Stage 3
    content_validator.py          Stage 4 (per-tag format/codes/NVR checks)
    cross_field_validator.py      Stage 5 (message-level rules across different tags, e.g. C1/C2/C3)

tests/
  test_file_structure.py      Single parametrized test, driven by scenario data

utils/
  expected_results.py         TC001-TC076 scenario data (file name, expected result, is_edge_case)

data/file_structure/          Input .txt fixtures, one per scenario (or shared baseline)
config/rules.json             MT700 field rules: presence, format, codes, NVR
run_tests.ps1                 pytest -> allure generate, in one step
```

## Known limitations of this POC (intentional scope boundary)

- **Content validation covers 21 of the 39 MT700 tags** — see "Content
  Validation Coverage — Tag by Tag" above for the full covered/not-yet-covered
  breakdown.
- **One soft usage rule remains unautomated**: tag 58a "must be present if
  confirmation instructions (tag 49) is MAY ADD or CONFIRM." This is a
  cross-field rule like C1/C2/C3, but it isn't expressed in `rules.json`'s
  structured `message_level_network_validated_rules` array the way C1/C2/C3
  are, so `cross_field_validator.py` doesn't see it yet.
- **Single message type (MT700 only)** — `config/rules.json` is flat and
  MT700-only. The pipeline's presence/tag-identifier/sequence/cross-field
  stages are already fully rules.json-driven and would work unchanged
  against another SWIFT message type's rules file; `content_validator.py`
  is the one stage that would need real work (it dispatches per-tag by a
  single flat `_CHECKS` table, not per `(message_type, tag)` — see its
  module docstring for the intended extension pattern before building this).
- **No UI screenshot or DB snapshot evidence** — this is a pure
  file-read-and-validate engine with no UI or database in play. The
  filtered execution log, raw input, and validation-report JSON
  attachments are the evidence trail in the interim.
- **Test scenario data is defined in `utils/expected_results.py` as plain
  Python**, not read from the xlsx test matrix — the xlsx is kept as a
  separate design/review artifact by explicit decision, not a runtime
  dependency of the test suite.

