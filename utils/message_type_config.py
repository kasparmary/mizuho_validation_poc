"""
Message-type registry loader — resolves which message type's rules file,
input-fixture directory, and scenario CSV the pytest suite should use for
this run.

Resolution order: the MT_TARGET environment variable, if set, names the
active message type; otherwise config/message_types.json's own "default"
key is used. This is deliberately an environment-variable override rather
than a pytest CLI flag, so switching message types never requires any
pytest-level argument-parsing code (a pytest_addoption hook, etc.) — the
registry file plus one env var is the entire mechanism, keeping "add a
message type" a pure data change, consistent with the rest of this
project's rules-driven design.

Usage:
    from utils.message_type_config import resolve_active_message_type
    active = resolve_active_message_type()
    active.message_type   # "MT700"
    active.rules_path     # "config/MT700/rules.json"
    active.data_dir       # "data/MT700"
    active.scenarios_path # "data/MT700/expected_results.csv"

To run against a different registered message type:
    $env:MT_TARGET = "MT730"; pytest        (PowerShell)
    MT_TARGET=MT730 pytest                  (bash)
"""

import json
import os
from pathlib import Path
from typing import NamedTuple, Optional

_PROJECT_ROOT = Path(__file__).parent.parent
_REGISTRY_PATH = _PROJECT_ROOT / "config" / "message_types.json"
_ENV_VAR = "MT_TARGET"


class MessageTypeConfig(NamedTuple):
    message_type: str
    rules_path: str
    data_dir: str
    scenarios_path: str


def _load_registry(registry_path: Path) -> dict:
    with open(registry_path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_active_message_type(registry_path: Optional[Path] = None) -> MessageTypeConfig:
    registry_path = registry_path or _REGISTRY_PATH
    registry = _load_registry(registry_path)

    message_type = os.environ.get(_ENV_VAR) or registry["default"]
    entry = registry["message_types"].get(message_type)
    if entry is None:
        available = ", ".join(sorted(registry["message_types"]))
        raise ValueError(
            f"Unknown message type '{message_type}' (from {_ENV_VAR} env var or "
            f"registry default) — no entry in {registry_path}. Registered: {available}."
        )

    return MessageTypeConfig(
        message_type=message_type,
        rules_path=entry["rules"],
        data_dir=entry["data_dir"],
        scenarios_path=entry["scenarios"],
    )
