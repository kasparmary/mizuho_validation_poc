---
name: mt700-tag-validation
description: Use when adding content validation for an MT700 SWIFT tag that isn't yet covered (check docs/content-validator-shape-taxonomy.md's "Coverage" line, or run Step 0's audit), or when asked to add/extend test coverage for an existing tag. Covers authoring a rules.json `shape` entry (or, rarely, a new shape-kind interpreter) and creating matching positive/negative/edge test data. Trigger phrases - "add validation for tag X", "create test data for tag X", "cover the remaining MT700 tags", "which tags are missing checks".
---

# MT700 tag validation + test data

`content_validator.py` is a rules-driven interpreter (see
`docs/content-validator-shape-taxonomy.md` for the full design): a small,
fixed set of generic `_interp_*` functions, one per shape *kind*, dispatched
by each tag's own `shape["kind"]` in `rules.json`. There is no per-tag
Python function. Adding a tag whose rule fits an existing shape kind means
adding data to `rules.json`, not writing Python — that's most of what this
skill now does. Only a genuinely novel shape (not one of the 9 kinds below)
needs new interpreter code, and even then it's one new function shared by
every future tag with that shape, not a per-tag one.

All 39 MT700 tags are currently covered (`find_uncovered_tags_with_rules()`
returns empty) — this skill now mainly applies to (a) a future message type
whose tags need `shape` entries of their own, or (b) extending/adjusting an
existing tag's shape or test coverage.

If invoked with an argument (a tag id like `44A`, `78`, `39A`), treat that as
the target tag. Otherwise ask the user which tag(s), or run the audit in
Step 0 and ask them to pick from the missing list.

## Step 0 — find out what's missing (skip if the target tag is already known)

```bash
.venv/Scripts/python.exe -c "
from src.engine import load_rules
from src.validators.content_validator import find_uncovered_tags_with_rules
from utils.message_type_config import resolve_active_message_type
active = resolve_active_message_type()
rules = load_rules(active.rules_path)
for w in find_uncovered_tags_with_rules(rules):
    print(w)
"
```

## Step 1 — read the rule

Find the tag's entry in the active message type's `rules.json` (e.g.
`config/MT700/rules.json` — `tags[]`, keyed by `"tag"`). Note:

- `format.raw` (or `format.options[]` for multi-option A/D/B fields) — informs
  which shape kind fits (see Step 2), but is no longer parsed at runtime —
  the interpreter reads `shape` directly, not `format.raw`.
- `presence` — Mandatory/Optional/Conditional. Conditional almost always means
  "see rule C1/C2/C3" (cross-field) — out of scope for a `shape` entry, needs
  no code/data change here at all; `presence_validator.py` already reads
  this field generically, and cross-field rules go in `cross_field_validator.py`
  (Step 3a).
- `codes` — an enum list, if present; the `shape.kind: "enum"` interpreter
  reads it directly, including `meaning` (shown in error messages).
- `network_validated_rules[]` — each has `text` + `error_code` (e.g. `T50`,
  `D81`). **Every entry needs an explicit `applies_to: [...]` list**, even
  on tags with only one NVR entry — do not assume "only one entry exists so
  it always applies." That exact assumption was tried, found wrong (a
  single-entry NVR that only covers part of a tag's possible violations —
  see tag 20's slash-boundary-only T26 wrongly attaching to its unrelated
  max-length violation before this was fixed), and removed. The label(s) in
  `applies_to` should match `format.subfield_labels` (or the composite
  subfield `name`s you're about to define in Step 2) — that's what each
  `_interp_*` violation's own `applies_to` argument is matched against.
- `usage_rules[]` — only enforce ones that constrain the tag's OWN value
  (e.g. 42a's "Party Identifier must not be present" → `shape.party_identifier.presence: "forbidden"`).
  Usage rules that reference a different tag (`depends_on: [...]`) are
  cross-field, same family as C1/C2/C3 below — see Step 3a, not Step 3.
- `rules.json`'s top-level `message_level_network_validated_rules[]`
  (SWIFT's C1/C2/C3, plus U1) — these are NOT per-tag, they compare tags
  against each other. Already handled generically by
  `src/validators/cross_field_validator.py` — see Step 3a.

## Step 2 — pick a shape kind, add a `shape` entry to rules.json

Full definitions and every current tag's mapping:
`docs/content-validator-shape-taxonomy.md`. Summary:

| Shape kind | Fits | Existing examples |
|---|---|---|
| `text` | Bounded free text, optional `no_slash_boundary` constraint | 20 |
| `enum` | Value must be in `codes[]` | 40A, 49 |
| `date_yymmdd` | `6!n` calendar date | 31C, 44C |
| `multiline` | `N*Mx` narrative, optional single-group account prefix (`[/Mx]`) | 42C, 44D, 50, 59 |
| `currency_amount` | `N!aMd` currency + decimal amount | 32B |
| `bic_or_name` | Option A (BIC) / D (Name-Address), optional 2-group Party Identifier (`[/N!a][/Mx]`); variant flags for a trailing code subfield (41a) or a bare-location Option B (57a) | 41a, 42a, 51a, 58a, 53a, 57a |
| `composite` | Multiple subfields, separator-delimited (e.g. `27`'s `Number/Total`) or positional/concatenated (e.g. `31D`'s `Date`+`Place`); subfield types include `fixed_numeric` (exact length, e.g. `1!n`), `numeric` (variable length up to max, e.g. `3n`), `date_yymmdd`, `text`; positional subfields can use `stop_at` instead of a fixed `length` when the subfield's own length varies (e.g. `48`'s `3n[/35x]`) | 27, 31D, 39A, 48 |
| `conditional_narrative` | Code + narrative, narrative gated on one specific code value | 40E |
| `structured_charges_or_info` | Per-line state machine: code block / continuation / narrative, narrative must be last | 71D, 72Z |

If the tag's format matches one of these, write its `shape` object directly
into that tag's `rules.json` entry (see the tag 27 example in
`docs/content-validator-shape-taxonomy.md` for the exact JSON shape) —
**no Python change at all.**

If genuinely nothing fits, that's a new shape kind: write one new
`_interp_<kind>()` function in `content_validator.py`, register it in
`_INTERPRETERS`, and update the taxonomy doc. This should be rare.

## Step 3 — cross-check the applies_to and NVR wiring

- Update `docs/content-validator-shape-taxonomy.md`'s "All 39 tags mapped"
  table row and the "Coverage" count for this tag.
- A per-tag `depends_on` usage rule (references a different tag) can't be
  expressed in `shape` — see Step 3a instead.

## Step 3a — cross-field rules (C1/C2/C3-style) go in `cross_field_validator.py`, not here

These ARE in scope — `rules.json`'s `message_level_network_validated_rules`
array is machine-readable specifically so they can be enforced, and
`src/validators/cross_field_validator.py` already evaluates it generically
by `dependency_type`:

| `dependency_type` | Meaning | Existing example |
|---|---|---|
| `co_presence` | if any of `tags_involved` is present, all must be | C1 (42C/42a) |
| `mutual_exclusion` | at most one of `tags_involved` may be present | C3 (44C/44D) |
| `mutual_exclusion_grouped` | at most one of `groups[]` may have any member present | C2 ({42C,42a} / {42M} / {42P}) |

If a new tag's cross-field rule fits one of these three patterns, just add
the rule object to `rules.json`'s `message_level_network_validated_rules`
array — no code change needed, same as adding a tag to `presence_validator`'s
mandatory-tag check. Only write a new evaluator function (and register it in
`_EVALUATORS`) if the rule genuinely doesn't fit any existing
`dependency_type`.

A per-tag `depends_on` usage rule that isn't a hard presence/exclusion
constraint (e.g. "special info should be specified in 39A or 39C", most of
which are `confidence: "implied"` rather than `"confirmed"`) is a softer,
harder-to-automate case — flag it to the user rather than assuming it needs
the same treatment as C1/C2/C3.

## Step 4 — sanity-check the interpreter directly, before touching test data

This step has caught real bugs before — a hand-typed "36-char" string that
was actually 34 chars (silently making a negative test pass for the wrong
reason), and the `applies_to` NVR-matching bugs described in Step 1. Never
skip it:

```bash
.venv/Scripts/python.exe -c "
from src.engine import load_rules
from src.validators import content_validator as cv
from utils.message_type_config import resolve_active_message_type
rules = load_rules(resolve_active_message_type().rules_path)
t = next(x for x in rules['tags'] if x['tag'] == '<TAG>')
shape = t['shape']
cases = [
    ('label', 'sample value'),
    ...
]
for label, val in cases:
    v = cv._INTERPRETERS[shape['kind']](val, shape, t)
    if v is None:
        print(f'{label:25} -> VALID')
    else:
        code = v['code_override'] or cv._resolve_error_code(t, v['applies_to'])
        print(f'{label:25} -> INVALID: {v[\"detail\"]}' + (f' [{code}]' if code else ''))
"
```

Cover every branch the interpreter can take for this shape/tag combination
(see Step 5) before moving on — confirm both the pass/fail outcome AND the
exact error text (**and that the bracketed error code is correct or
correctly absent** — this is exactly what the `applies_to` bugs looked
like), since the test's `expected_error_substring` must match what the
interpreter actually emits, not what you assume it emits.

## Step 5 — design the test matrix (branch coverage, not vibes)

For each `if`/`return` branch in the new function (and any shared helper it
calls), plan one case:

- One positive per distinct valid shape (e.g. both Option A and Option D,
  or both an 8-char and 11-char BIC if the format allows a length range).
- One negative per validation branch (bad shape, code-list violation, each
  distinct NVR, each length/line-count limit).
- Edge cases at exact boundaries: `max_len` vs `max_len + 1`, `max_lines` vs
  `max_lines + 1`, empty value, a value that's syntactically close to valid
  but should still fail (e.g. TC033's "confusable" ICC code).
- If the tag has a C1/C2/C3-style rule (Step 3a), add cases for THAT too:
  one negative per way the rule can be violated, and a positive proving each
  legal combination — see TC057-TC060 (42C without 42a, the 42-group present
  alongside 42M, 44C+44D together, and 42M alone) for the shape these take.

A case that doesn't correspond to a distinct branch in the function is
probably redundant — skip it rather than pad the count.

## Step 6 — build fixture files

- Get the full canonical field order once:
  ```bash
  .venv/Scripts/python.exe -c "
  import json
  from utils.message_type_config import resolve_active_message_type
  rules = json.load(open(resolve_active_message_type().rules_path, encoding='utf-8'))
  for t in rules['tags']:
      print(t['field_no'], t['tag'])
  "
  ```
- Start from `data/<TYPE>/baseline_sample_header_data.txt` (e.g.
  `data/MT700/baseline_sample_header_data.txt` — or an existing extended
  baseline if one already carries the fields you need) and insert/mutate
  **only the one field under test**, keeping every other tag valid — this
  isolates the failure to the fault you intend.
- Insert the new tag at its correct position relative to tags already in
  the file, per field_no order, or `sequence_validator` will fail the file
  for the wrong reason.
- Reuse an existing fixture across multiple positive `ExpectedOutcome`
  entries when it already carries a valid value for the tag (see how
  `baseline_sample_header_data.txt` backs several TCs, or how TC038/TC039
  share one file) — don't create a new file just to duplicate an assertion.
- Name new files `tag<TAG>_<scenario>.txt`, matching the existing
  convention (`tag42a_invalid_shape.txt`, `tag44D_exceeds_6_lines.txt`, …).

## Step 7 — verify boundary values programmatically, not by counting

Before wiring a length/line-count edge case into `expected_results.py`,
confirm the fixture's actual value matches what you intended:

```bash
.venv/Scripts/python.exe -c "
with open('data/MT700/<file>.txt', encoding='utf-8') as f:
    for line in f:
        if line.startswith(':<TAG>:'):
            val = line.rstrip(chr(10)).split(':<TAG>:')[1]
            print(len(val), repr(val))
"
```

For multi-line values, sum/inspect all continuation lines, not just the
first. This is the single highest-value check in this whole workflow —
apply it to every boundary-length or line-count fixture, no exceptions.

## Step 8 — wire `expected_results.csv`

- Scenario data lives in `data/<TYPE>/expected_results.csv` (e.g.
  `data/MT700/expected_results.csv`), NOT `utils/expected_results.py`
  (that file only resolves the active message type via
  `utils.message_type_config` and loads its CSV — don't add scenario rows
  there). Continue the `TC0NN`
  numbering from the last row in the CSV. Columns: `test_id`, `file_name`,
  `scenario`, `expected_valid` (`True`/`False`), `expected_error_substring`
  (blank for positive cases), `is_edge_case` (`True`/`False`).
- `expected_error_substring` must be a literal substring of the error text
  the function actually returns (verified in Step 4) — not the NVR's
  `error_code` from rules.json if the function doesn't happen to emit that
  exact code for that branch (see the 40E `[D81]` vs `[ADVISORY]`
  distinction — rules.json's error codes don't always map 1:1 to every
  related branch).
- Set `is_edge_case=True` for boundary-value and extreme-input cases; leave
  it `False` for plain positive/negative cases. This drives the Allure
  "Positive Cases / Negative Cases / Edge Cases" Behaviors grouping in
  `tests/test_file_structure.py` automatically — no other wiring needed.

## Step 9 — run and confirm

```powershell
.\run_tests.ps1
```

Confirm the new TCs pass AND the full existing suite still passes (a
regression here almost always means a canonical-order mistake in a fixture,
not a validator bug — check `sequence_validator`'s debug log in the
failure output first).
