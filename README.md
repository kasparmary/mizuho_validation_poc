# MT700 Validation POC

Validates an MT700 input file (Documentary Credit issuance message, Block 4)
against the SWIFT Category 7 Message Reference Guide, across three concerns:

- **File structure** — presence of mandatory tags, correct tag sequence (per
  the guide's field `No.` order), and tag-identifier legitimacy (no
  duplicates, no unrecognized tags, uppercase wire format).
- **Field content** — tag *values* checked against format, code lists, and
  network-validated rules (NVR) from the active message type's rules file
  (`config/MT700/rules.json` by default — see "Message type registry"
  below), for all 39 of the 39 MT700 tags (see "Content Validation
  Coverage — Tag by Tag" below for the full breakdown).
- **Cross-field rules** — message-level rules that compare DIFFERENT tags
  against each other (SWIFT's C1/C2/C3: 42C/42a co-presence, 42-group vs 42M
  vs 42P mutual exclusion, 44C/44D mutual exclusion; plus U1, a usage-rule
  promoted to message level: 58a must be present if 49 is MAY ADD or
  CONFIRM), driven generically by `rules.json`'s
  `message_level_network_validated_rules` array.

Covers **142 scenarios (TC001–TC142)** in `data/MT700/expected_results.csv`.
The first ~33 trace back to the original MT700 test matrix
(`docs/MT700_Test_Scenarios_sample_header_data.xlsx`); everything from
TC034 onward was added since, extending coverage tag by tag and rule by rule
— the CSV itself and `utils/expected_results.py`'s docstring are the
authoritative source for what each scenario covers, not this README.

## Message type registry

`config/message_types.json` is the single source of truth for which message
types the framework knows about, and where each one's three artifacts live:

```json
{
  "default": "MT700",
  "message_types": {
    "MT700": {
      "rules": "config/MT700/rules.json",
      "data_dir": "data/MT700",
      "scenarios": "data/MT700/expected_results.csv"
    }
  }
}
```

The pytest suite always validates exactly **one active message type per
run**, resolved by `utils/message_type_config.py`: the `MT_TARGET`
environment variable if set, otherwise the registry's `"default"`. Nothing
in `src/` — the extractor, engine, or any validator — has any awareness of
message type at all; only this resolution step (used by `conftest.py`'s
`rules` fixture and `utils/expected_results.py`'s scenario loader) decides
which files get loaded for a given run.

```powershell
pytest                        # runs the registry's default (MT700)
$env:MT_TARGET = "MT730"; pytest   # runs MT730 instead, once it's registered
```

Adding a second message type is a **data-only** change: create its
`rules.json` (with `shape` entries per `docs/content-validator-shape-taxonomy.md`),
its own `data/<TYPE>/` fixture folder and `expected_results.csv`, and one
new entry in `config/message_types.json` — no code in `conftest.py`,
`test_file_structure.py`, or anywhere in `src/` needs to change.

Running two message types' full suites *at the same time* (true parallel
invocations) is not yet safe — both currently share
`reports/allure-results/` and `reports/logs/`, and `--clean-alluredir`
from one invocation can wipe results the other is still writing. Run them
sequentially (once per `MT_TARGET`) until per-message-type report paths
are added.

## Content Validation Coverage — Tag by Tag

All 39 of the 39 MT700 tags have field-content validation (format, code
list, and network-validated-rule checks on the tag's *value*), via a
rules-driven interpreter in `content_validator.py` — 9 generic shape kinds
(`text`, `enum`, `date_yymmdd`, `multiline`, `currency_amount`,
`bic_or_name`, `composite`, `conditional_narrative`,
`structured_charges_or_info`), dispatched by each tag's own
`shape["kind"]` in `rules.json`. No per-tag Python function; full
design and the complete 39-tag mapping: `docs/content-validator-shape-taxonomy.md`.

**All 39 tags' error codes and constraints now come from an explicit
`rules[]` array**, not `network_validated_rules[]` (fully retired — zero
tags carry it anymore). Every constraint is its own object: `rule_id`,
`subfield`, `rule_type`, `constraint`, `severity` (`hard`/`advisory`),
`error_code` (`null` when a constraint has no official SWIFT NVR backing —
e.g. pure length limits), `source_section` (which part of the SWIFT spec
it traces back to — `Format`, `Codes`, `Network Validated Rules`, ...),
`condition` (for constraints that only apply given another subfield's
value — e.g. tag 40E's Narrative rules only fire when Applicable Rules is
OTHR), and `description`. `shape` itself now holds *only* parsing metadata
(how to decompose a value into named subfields — separators, positional
lengths, BIC-branch detection) for every tag except `structured_charges_or_info`
(71D, 72Z), which is a stateful per-line check with no fixed subfields to
decompose, so it's handled as a single parser step instead (`rules: []`
there is intentionally empty, not a gap). `docs/rules_pattern.csv` is a
flattened, spreadsheet-reviewable export of every rule across every tag —
one row per constraint, with full SWIFT-spec traceability.

Tag 51a additionally validates its BIC against a small illustrative
reference set (`config/bic_directory_sample.json`) to make the five
distinct SWIFT BIC-validation codes (T27/T28/T29/T45/C05) independently
testable — see "Known limitations" below for exactly how far this goes
(and doesn't go).

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

## Validating a single file (CLI)

To check one MT700 file directly — e.g. a real production file dropped in a
bank inbox — without touching the pytest suite or `expected_results.csv`:

```powershell
python validate.py --file "filepath"
```

### CLI options

| Option | Required | Description |
|---|---|---|
| `--file` | Yes | Path to the MT700 Block 4 `.txt` file to validate. Any path on disk — relative, absolute, or a UNC network share (`\\server\share\...`). Not limited to files under `data/MT700/`. |
| `--rules` | No | Path to the rules file (default: `config/MT700/rules.json`). Only needed to validate against a different rule set — e.g. a different message type's rules.json, once one exists. Note `validate.py` reads this flag directly and does **not** go through `config/message_types.json` — that registry only drives the pytest suite (see "Message type registry" above), so `validate.py` can validate against any rules file, including one that isn't registered. |
| `--verbose` | No | Prints the full stage-by-stage trace (presence → tag identifier → sequence → content → cross-field), not just the final summary — useful for seeing exactly *where* in the pipeline an issue was found. |

### Examples

```powershell
python validate.py --file "C:\inbox\LC_20260901_001.txt"
python validate.py --file "C:\inbox\LC_20260901_001.txt" --verbose
python validate.py --file "\\zucisystems.com\Kaspar-bkp-2023-10-09\Automation\Mizuho\full_mt700_all_tags_sample.txt"
python validate.py --file some_file.txt --rules config/MT700/rules.json
```

**Always wrap the path in double quotes**, especially for Windows paths with
backslashes (`C:\...`) or UNC network shares (`\\server\share\...`). Without
quotes, a shell can split the path on its own special characters, and
argparse can then misread a fragment of the path as an unrecognized option
(e.g. `unrecognized arguments: - zucisystems.com\...`) instead of the file
path you meant — quoting the whole path avoids that entirely, on any shell.

Prints a pass/fail summary and every issue found; exits `0` if valid, `1`
otherwise, so it's usable in a shell script or CI step.

## What each test's Allure report entry contains

- **Issues Found (missing/invalid items only)** — WARNING/ERROR-level log
  records only (INFO/DEBUG "everything passed" noise is filtered out), also
  written to `reports/logs/<test_id>.log` as a standalone file.
- **Raw Input** — the exact `.txt` fixture fed to the engine, unmodified —
  lets you compare the original SWIFT message text against the result.
- **Validation Report** — the structured pass/fail + error list for each of
  the five pipeline stages (presence, tag identifier, sequence, content,
  cross-field).

Tests are grouped in the report's **Behaviors** tab (not just Suites) —
**Epic** is the active message type (e.g. "MT700 Validation"), set
dynamically per scenario via `allure.dynamic.epic(...)`, not a hardcoded
decorator, so a run against a different `MT_TARGET` reports under its own
Epic automatically — and within that, **Story** is Positive Cases /
Negative Cases / Edge Cases, based on each scenario's `expected_valid` and
`is_edge_case` columns in `expected_results.csv`.

## Pipeline

```
raw file text
    -> extractor.extract()          ordered list of (tag, value), CRLF/LF-safe,
                                     multi-line continuations joined correctly
    -> presence_validator.check()       all Mandatory tags present & non-empty?
    -> tag_identifier_validator.check() no repeats, no unknown tags, uppercase identifiers?
    -> sequence_validator.check()       present (recognized) tags in canonical field_no order?
    -> content_validator.check()        tag values conform to format/codes/NVR rules?
    -> cross_field_validator.check()    message-level rules across DIFFERENT tags (SWIFT's C1/C2/C3, plus U1)?
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
  message_type_config.py      Resolves the active message type (MT_TARGET env var, or
                               config/message_types.json's "default") to its rules/data/scenarios paths
  expected_results.py         Loads scenario data from the active type's expected_results.csv;
                               defines ExpectedOutcome; exposes ACTIVE_MESSAGE_TYPE
  (expected_results.csv now lives under data/<TYPE>/, not here — see below)

config/message_types.json     The message-type registry — one entry per registered type, plus
                               which one is "default"
config/MT700/rules.json       MT700 field rules: presence, format, codes, a `shape` (parsing
                               metadata) and `rules[]` (explicit, traceable constraints —
                               replaces network_validated_rules[] for all 39 tags) per tag —
                               see docs/content-validator-shape-taxonomy.md
config/iso4217.json           Full ISO 4217 currency/decimal-precision reference table (shared
                               across every message type — not per-type, since currency codes
                               don't vary by SWIFT message type)
config/bic_directory_sample.json  Small illustrative BIC reference set — NOT a real SWIFT
                               directory — used only by tag 51a to make error codes
                               T27/T28/T29/T45/C05 independently testable locally

docs/rules_pattern.csv        Flattened, spreadsheet-reviewable export of every tag's rules[]
                               (one row per constraint) — regenerate after editing rules.json

data/MT700/                   MT700's own fixtures + scenario CSV, self-contained:
  *.txt                         Input .txt fixtures, one per scenario (or shared baseline)
  expected_results.csv          TC001-TC142 scenario data (file name, expected result, is_edge_case) —
                                 edit THIS file to add/change scenarios, not expected_results.py

validate.py                   CLI: validate any file by path, outside the pytest suite
                               (python validate.py --file <path> [--rules <path>]) — reads
                               --rules directly, independent of config/message_types.json
run_tests.ps1                 pytest -> allure generate, in one step
```

## Known limitations of this POC (intentional scope boundary)

- **Content validation covers all 39 of the 39 MT700 tags** — see "Content
  Validation Coverage — Tag by Tag" above. `content_validator.py` is a
  rules-driven interpreter (9 generic shape kinds, dispatched by each tag's
  `shape["kind"]` in `rules.json` — no per-tag Python function); extending
  to a new message type's tag is a `rules.json`-only change for anything
  fitting an existing shape kind. Still open: automating more than 1 of the
  ~10+ `usage_rules[].depends_on` cross-field relationships, and
  character-set (charset) validation — confirmed live: a value with `@#`
  (outside SWIFT's `x`-charset) or raw control characters/emoji (outside
  `z`-charset) is currently accepted as long as it's within the length
  limit, since every shape kind only checks length/line-count/position,
  never character class. Full design: `docs/content-validator-shape-taxonomy.md`.
- **BIC "must be registered" checks are documented but only enforced for
  one tag.** Every `bic_or_name` tag's `rules[]` states that a BIC must be
  a *registered* financial institution (per SWIFT's T27/T28/T29/T45/C05),
  but only tag 51a actually checks a BIC against something
  (`config/bic_directory_sample.json` — a small, explicitly illustrative
  set, not a real SWIFT directory). Every other `bic_or_name` tag (41a,
  42a, 53a, 57a, 58a) only verifies a BIC's *shape* (8 or 11 alphanumeric
  characters) — a well-formed but entirely fabricated BIC passes. This is
  named explicitly in each of those tags' own `rules[]` entries
  (`rule_type: "external_reference"`, `constraint.reference` states the
  gap directly) — not a silent omission, but a real one, and extending
  51a's directory check to the other five would be the natural next step
  if this stops being a POC.
- **Only one message type is actually registered (MT700)** — the
  *mechanism* for more is in place (`config/message_types.json` +
  `utils/message_type_config.py`, see "Message type registry" above), and
  has been cross-checked against the real MT730 and MT701 specs (8 of
  MT730's 9 tags, and the range-constrained part of MT701's tag 27, would
  need zero new Python — pure data in a new `rules.json`). What's missing
  for a second real message type is authoring its rules.json + fixtures +
  scenarios, not framework work.
- **No UI screenshot or DB snapshot evidence** — this is a pure
  file-read-and-validate engine with no UI or database in play. The
  filtered execution log, raw input, and validation-report JSON
  attachments are the evidence trail in the interim.
- **Test scenario data lives in `data/MT700/expected_results.csv`**, not
  read from the xlsx test matrix — the xlsx is kept as a separate
  design/review artifact by explicit decision, not a runtime dependency of
  the test suite.
- **True parallel runs of two message types are not yet safe** — both
  would currently share `reports/allure-results/` and `reports/logs/`,
  and `--clean-alluredir` from one invocation can wipe the other's
  in-flight results (confirmed by running two concurrent `pytest`
  invocations and observing an inconsistent, non-reproducible result-file
  count). Run sequentially (once per `MT_TARGET`) until per-message-type
  report paths are added — the full suite only takes ~2 seconds, so this
  costs little in practice.

