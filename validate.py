"""
CLI entry point — validate a single MT700 file from any path, without
editing utils/expected_results.py or running the pytest suite.

Usage:
    python validate.py --file C:/inbox/LC_20260901_001.txt
    python validate.py --file some_file.txt --rules config/MT700/rules.json

Exit code: 0 if the file is valid, 1 if invalid or if the file/rules path
can't be read — so this is scriptable in a shell pipeline or CI step.
"""

import argparse
import logging
import sys

from src.engine import validate, load_rules


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a single MT700 SWIFT message file.")
    parser.add_argument("--file", required=True, help="Path to the MT700 Block 4 .txt file to validate.")
    parser.add_argument("--rules", default="config/MT700/rules.json", help="Path to the rules.json file (default: config/MT700/rules.json).")
    parser.add_argument("--verbose", action="store_true", help="Show full stage-by-stage log output, not just the summary.")
    args = parser.parse_args()

    logger = logging.getLogger("validate_cli")
    logger.propagate = False
    if args.verbose:
        # Full stage-by-stage trace, including the same errors the summary
        # below repeats — that duplication is expected: --verbose is for
        # seeing WHERE in the pipeline something happened, not just what.
        logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(levelname)-8s %(message)s"))
        logger.addHandler(handler)
    else:
        # Default: no log noise at all — only the clean summary at the end.
        logger.addHandler(logging.NullHandler())

    try:
        rules = load_rules(args.rules)
    except (OSError, ValueError) as e:
        print(f"ERROR: could not load rules file '{args.rules}': {e}")
        return 1

    try:
        report = validate(args.file, rules, logger=logger)
    except OSError as e:
        print(f"ERROR: could not read input file '{args.file}': {e}")
        return 1

    print()
    print(f"File: {report.file_name}")
    print(f"Result: {'VALID' if report.overall_valid else 'INVALID'}")
    if not report.overall_valid:
        print(f"\n{len(report.all_errors())} issue(s) found:")
        for err in report.all_errors():
            print(f"  - {err}")

    return 0 if report.overall_valid else 1


if __name__ == "__main__":
    sys.exit(main())
