# MT700 Validation POC

Validates an MT700 input file (Documentary Credit issuance message, Block 4)
against the SWIFT Category 7 Message Reference Guide, across two concerns:

- **File structure** — presence of mandatory tags, correct tag sequence (per
  the guide's field `No.` order), and tag-identifier legitimacy (no
  duplicates, no unrecognized tags, uppercase wire format).
- **Field content** — tag *values* checked against format, code lists, and
  network-validated rules (NVR) from `config/rules.json`, for the tags
  currently covered: `27`, `40A`, `20`, `31C`, `40E`.

Covers test scenarios **TC001–TC033** from the MT700 test matrix
(`docs/MT700_Test_Scenarios_sample_header_data.xlsx`), skipping TC017 (folded
into the baseline CRLF fixture already used by TC001–003) and TC026/TC035/TC039
(flagged in the source matrix as open interpretation questions, not yet
resolvable into a hard pass/fail assertion).

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

- **Execution Log** — the full log trace for that test's run (extraction,
  presence/sequence/duplicate/content stage-by-stage detail), also written to
  `reports/logs/<test_id>.log` as a standalone file.
- **Extracted Tags** — the exact (tag, value) list the engine parsed from the
  input file, in order — lets you see precisely what the parser saw.
- **Validation Report** — the structured pass/fail + error list for each of
  the four pipeline stages.

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
  expected_results.py         TC001+ scenario data (file name, expected result — see the file
                               itself for the current count, this README isn't kept in sync)

data/file_structure/          Input .txt fixtures, one per scenario (or shared baseline)
config/rules.json             MT700 field rules: presence, format, codes, NVR
run_tests.ps1                 pytest -> allure generate, in one step
```

## Known limitations of this POC (intentional scope boundary)

- **Content validation covers 5 of the 39 MT700 tags** (`27`, `40A`, `20`,
  `31C`, `40E`) — the set exercised by TC018–038. Extending to another tag
  means adding one check function in `content_validator.py` plus its
  dispatch entry; the rest of the pipeline needs no changes.
- **No UI screenshot or DB snapshot evidence** — this is a pure
  file-read-and-validate engine with no UI or database in play. The
  execution log and extracted-tag/report JSON attachments are the evidence
  trail in the interim.
- **No country/product configuration layering** — `config/rules.json` is
  deliberately kept flat and MT700-only; a layered override design was
  discussed but not implemented, to avoid building ahead of a deprioritized
  requirement.
- **Test scenario data is defined in `utils/expected_results.py` as plain
  Python**, not read from the xlsx test matrix — the xlsx is kept as a
  separate design/review artifact by explicit decision, not a runtime
  dependency of the test suite.
- **Advisory/open-interpretation rules are excluded** — TC026 (usage-rule
  advisory, not a hard NVR), TC035 (century-window ambiguity for 2-digit
  years, not specified in the guide), and TC039 (D81 directional ambiguity
  for OTHR without narrative) are flagged in the source test matrix as
  unresolved questions, not coded as assertions here.

