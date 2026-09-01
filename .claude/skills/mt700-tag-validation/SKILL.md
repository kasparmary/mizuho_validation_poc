---
name: mt700-tag-validation
description: Use when adding content validation for an MT700 SWIFT tag that isn't yet covered in src/validators/content_validator.py (check the "Covers tags..." line in its module docstring), or when asked to add/extend test coverage for an existing tag. Covers writing the _check_<TAG> function and creating matching positive/negative/edge test data. Trigger phrases - "add validation for tag X", "create test data for tag X", "cover the remaining MT700 tags", "which tags are missing checks".
---

# MT700 tag validation + test data

Adds one tag's content validation to this repo the same way 42a/51a/44D/etc.
were added earlier in this project: read the rule from `config/rules.json`,
reuse a shared helper where the shape matches, write the check function,
then build a test matrix that hits every branch the function can take —
not just "one positive, one negative".

If invoked with an argument (a tag id like `44A`, `78`, `39A`), treat that as
the target tag. Otherwise ask the user which tag(s), or run the audit in
Step 0 and ask them to pick from the missing list.

## Step 0 — find out what's missing (skip if the target tag is already known)

```bash
.venv/Scripts/python.exe -c "
import json, re
rules = json.load(open('config/rules.json', encoding='utf-8'))
src = open('src/validators/content_validator.py', encoding='utf-8').read()
checked = set(re.findall(r'\"([^\"]+)\":', re.search(r'_CHECKS = \{(.*?)\n\}', src, re.S).group(1)))
for t in rules['tags']:
    if t['tag'] not in checked:
        print(t['field_no'], t['tag'], '|', t['presence'], '|', t['format'])
"
```

## Step 1 — read the rule

Find the tag's entry in `config/rules.json` (`tags[]`, keyed by `"tag"`). Note:

- `format.raw` (or `format.options[]` for multi-option A/D/B fields) — the shape.
- `presence` — Mandatory/Optional/Conditional. Conditional almost always means
  "see rule C1/C2/C3" (cross-field) — that's out of scope for
  `content_validator.py` (see its module docstring); presence itself needs no
  code change anywhere, `presence_validator.py` already reads this field
  generically.
- `codes` — an enum list, if present.
- `network_validated_rules[]` — each has `text` + `error_code` (e.g. `T50`,
  `D81`). Every NVR listed here should show up as a distinct branch in the
  check function, tagged with its bracketed code, e.g.
  `f"...{value}... [T50]."`
- `usage_rules[]` — only enforce ones that constrain the tag's OWN value
  (e.g. 42a's "Party Identifier must not be present") in
  `content_validator.py`. Usage rules that reference a different tag
  (`depends_on: [...]`) are cross-field, same family as C1/C2/C3 below —
  see Step 3a, not Step 3.
- `rules.json`'s top-level `message_level_network_validated_rules[]`
  (SWIFT's C1/C2/C3) — these are NOT per-tag, they compare tags against each
  other (co-presence, mutual exclusion). Already handled generically by
  `src/validators/cross_field_validator.py`, driven by that array's
  `dependency_type` field (`co_presence` / `mutual_exclusion` /
  `mutual_exclusion_grouped`) — see Step 3a.

## Step 2 — pick a shape, reuse a helper if one already fits

`content_validator.py` is intentionally one function per tag, not a generic
interpreter — but several shapes recur and already have shared helpers:

| Shape | Helper | Existing examples |
|---|---|---|
| `6!n` calendar date (YYMMDD) | `_is_valid_yymmdd()` | 31C, 31D, 44C |
| `N*Mx` / `N*Mz` narrative (max N lines, M chars/line) | `_check_multiline(value, max_lines=N, max_line_len=M)` | 42C, 44D, 50, 59 |
| `[/1!a][/34x] 4!a2!a2!c[3!c]` (Option A/D BIC-or-Name/Address, optional leading Party Identifier) | `_split_party_identifier()` + `_check_bic_or_name_option()` | 42a, 51a |
| Fixed enum/code list | a `_TAG_CODES = {...}` set + `if value not in _TAG_CODES` | 40A, 40E, 41a, 49 |
| Anything else (subfield splits, currency/amount, etc.) | bespoke function | 27, 32B |

If the tag's format string matches one of the first three rows closely,
reuse that helper — don't re-derive the logic. `57a`'s third format option
(`[/1!a][/34x] [35x]`, Option B "bare Location") didn't fit
`_check_bic_or_name_option` unchanged — that helper rejects a spaceless
single-line value as "neither shape", but Option B explicitly allows one
(e.g. a bare city name). Resolved with a bespoke `_check_57a` (see
`content_validator.py`) that drops the free-text/space requirement for the
single-line case; reuse THAT as the template if another tag turns up with
the same 3-option A/B/D shape, rather than re-deriving it again.

## Step 3 — write `_check_<TAG>()`

- Add it near the other tag functions (roughly in field_no order, though
  this isn't strictly enforced elsewhere in the file).
- Register it in the `_CHECKS` dict.
- Update the module docstring's "Covers tags..." line.
- A per-tag `depends_on` usage rule (references a different tag) still
  can't be expressed here — see Step 3a instead of implementing it in
  `_check_<TAG>()`.

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

## Step 4 — sanity-check the function directly, before touching test data

This step caught a real bug earlier (a hand-typed "36-char" string that was
actually 34 chars, silently making a negative test pass for the wrong
reason). Never skip it:

```bash
.venv/Scripts/python.exe -c "
from src.validators.content_validator import _check_<TAG>
cases = [
    ('label', 'sample value'),
    ...
]
for label, val in cases:
    print(f'{label:25} -> {_check_<TAG>(val)!r}')
"
```

Cover every branch the function can take (see Step 5) before moving on —
confirm both the pass/fail outcome AND the exact error text, since the
test's `expected_error_substring` must match what the function actually
emits, not what you assume it emits.

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
  rules = json.load(open('config/rules.json', encoding='utf-8'))
  for t in rules['tags']:
      print(t['field_no'], t['tag'])
  "
  ```
- Start from `data/file_structure/baseline_sample_header_data.txt` (or an
  existing extended baseline if one already carries the fields you need)
  and insert/mutate **only the one field under test**, keeping every other
  tag valid — this isolates the failure to the fault you intend.
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
with open('data/file_structure/<file>.txt', encoding='utf-8') as f:
    for line in f:
        if line.startswith(':<TAG>:'):
            val = line.rstrip(chr(10)).split(':<TAG>:')[1]
            print(len(val), repr(val))
"
```

For multi-line values, sum/inspect all continuation lines, not just the
first. This is the single highest-value check in this whole workflow —
apply it to every boundary-length or line-count fixture, no exceptions.

## Step 8 — wire `expected_results.py`

- Continue the `TC0NN` numbering from the last entry in
  `utils/expected_results.py`.
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
