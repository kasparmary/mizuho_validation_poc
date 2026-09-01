"""
Shared pytest fixtures.

- `sys.path` setup so `from src...` / `from utils...` imports work regardless
  of where pytest is invoked from.
- `rules` fixture: loads config/rules.json once per test session.
- `test_logger` fixture: gives each test its own isolated logger. Only
  WARNING and ERROR records are ever captured — INFO/DEBUG "everything
  passed" noise (stage headers, per-tag pass confirmations, full extraction
  dumps) is filtered out at the handler level, so both the standalone .log
  file and the Allure evidence show only the missing/invalid items that
  actually matter, not a full history of what went right.
  The Allure evidence is rendered as HTML with the missing/invalid message
  text in bold, color-coded by severity (amber for warnings, red for
  errors), since a plain-text attachment cannot render bold at all.
"""

import logging
import sys
from datetime import datetime
from html import escape
from pathlib import Path

import allure
import pytest

PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.engine import load_rules  # noqa: E402

LOG_DIR = PROJECT_ROOT / "reports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# Only these levels are ever captured — INFO/DEBUG "passed" noise is dropped
# at the handler, not just hidden in the UI, so it never reaches the file or
# the report at all.
_CAPTURE_LEVEL = logging.WARNING


class _ListHandler(logging.Handler):
    """Collects log records as structured objects (not pre-formatted text) so
    the Allure HTML evidence can style each one individually by severity."""

    def __init__(self, level):
        super().__init__(level=level)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def _severity_color(levelno: int) -> str:
    return "#b91c1c" if levelno >= logging.ERROR else "#b45309"  # red / amber


def _build_html_evidence(records) -> str:
    if not records:
        return (
            "<html><body style='font-family:Arial,sans-serif;'>"
            "<p style='color:#15803d;font-weight:bold;'>No issues found — validation passed cleanly.</p>"
            "</body></html>"
        )

    rows = []
    for r in records:
        ts = datetime.fromtimestamp(r.created).strftime("%H:%M:%S")
        color = _severity_color(r.levelno)
        rows.append(
            "<div style='margin-bottom:6px;line-height:1.4;'>"
            f"<span style='color:#6b7280;font-family:monospace;font-size:12px;'>{ts} [{r.levelname}]</span> "
            f"<b style='color:{color};'>{escape(r.getMessage())}</b>"
            "</div>"
        )
    return "<html><body style='font-family:Arial,sans-serif;'>" + "".join(rows) + "</body></html>"


@pytest.fixture(scope="session")
def rules():
    return load_rules(str(PROJECT_ROOT / "config" / "rules.json"))


@pytest.fixture
def test_logger(request):
    test_id = getattr(getattr(request.node, "callspec", None), "id", request.node.name)
    safe_id = test_id.replace("/", "_").replace("\\", "_")

    logger = logging.getLogger(f"mt700.{safe_id}")
    logger.setLevel(logging.DEBUG)  # validators may still call .info()/.debug(); handlers filter them out
    logger.propagate = False

    list_handler = _ListHandler(level=_CAPTURE_LEVEL)
    logger.addHandler(list_handler)

    log_file_path = LOG_DIR / f"{safe_id}.log"
    file_handler = logging.FileHandler(log_file_path, mode="w", encoding="utf-8")
    file_handler.setLevel(_CAPTURE_LEVEL)
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(file_handler)

    yield logger

    if not list_handler.records:
        # Keep the file evidence honest too — an empty file reads as "did this even run?"
        with open(log_file_path, "a", encoding="utf-8") as f:
            f.write("No issues found — validation passed cleanly.\n")

    allure.attach(
        _build_html_evidence(list_handler.records),
        name="Issues Found (missing/invalid items only)",
        attachment_type=allure.attachment_type.HTML,
    )

    logger.removeHandler(list_handler)
    logger.removeHandler(file_handler)
    file_handler.close()
