"""Shared fixtures for the SW-E-P annotation test suite."""

import json
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from swep.config import Config  # noqa: E402
from swep.prompts import PromptSet  # noqa: E402
from swep.schema import ReviewRecord  # noqa: E402

PROMPTS_DIR = REPO_ROOT / "prompts"
SAMPLE_DATA = REPO_ROOT / "data" / "samples" / "sample_comments.jsonl"


def make_record(comment_id="c-1", **overrides):
    """Build a valid :class:`ReviewRecord` with sensible defaults."""
    values = {
        "comment_id": comment_id,
        "source": "file-level",
        "comment_text": "The `parse_config` function should validate the extension.",
        "review_diff": "@@ -1,3 +1,4 @@\n def parse_config(path):\n+    pass\n",
        "subsequent_changes": "@@ -1,3 +1,5 @@\n def parse_config(path):\n+    pass\n+    return None\n",
        "action_name": "code-review",
        "trigger": "automatic",
        "granularity": "file",
        "repo": "demo/repo",
        "pr_number": "1",
        "gold_label": None,
        "gold_issues": [],
        "synthetic": True,
    }
    values.update(overrides)
    return ReviewRecord(**values)


def base_config_payload(dataset_path, output_dir, **overrides):
    """Minimal YAML payload pointing at the repository prompts."""
    payload = {
        "run": {"name": "test-run", "limit": None, "log_level": "ERROR", "abort_on_record_error": False},
        "data": {"path": str(dataset_path), "format": "auto", "column_map": {}, "split": None},
        "llm": {
            "provider": "mock",
            "temperature": 0,
            "budget": {"max_usd": 100.0},
            "cache": {"enabled": False, "path": str(Path(output_dir) / "cache.sqlite3")},
            "max_parse_retries": 1,
        },
        "prompts": {
            "stage1": str(PROMPTS_DIR / "stage1.md"),
            "stage2": str(PROMPTS_DIR / "stage2.md"),
            "version": "test-v1",
        },
        "output": {"dir": str(output_dir)},
    }
    for section, values in overrides.items():
        if isinstance(values, dict) and isinstance(payload.get(section), dict):
            payload[section] = _deep_update(payload[section], values)
        else:
            payload[section] = values
    return payload


def _deep_update(base, override):
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_update(merged[key], value)
        else:
            merged[key] = value
    return merged


def write_config(tmp_path, dataset_path, **overrides) -> Config:
    """Write a YAML configuration under ``tmp_path`` and load it."""
    output_dir = tmp_path / "out"
    payload = base_config_payload(dataset_path, output_dir, **overrides)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return Config.load(config_path)


def write_jsonl(path, rows):
    with Path(path).open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return Path(path)


@pytest.fixture
def records_path(tmp_path):
    """A three-record JSONL dataset with mixed labels."""
    rows = [
        {
            "comment_id": "c-1",
            "source": "file-level",
            "comment_text": "`parse_config` should validate the extension before reading.",
            "review_diff": "@@ -1,2 +1,3 @@\n def parse_config(path):\n+    pass\n",
            "subsequent_changes": "@@ -1,2 +1,4 @@\n def parse_config(path):\n+    pass\n",
            "gold_label": "Valid-Fully",
        },
        {
            "comment_id": "c-2",
            "source": "file-level",
            "comment_text": "LGTM, thanks!",
            "review_diff": "@@ -5,1 +5,2 @@\n def f():\n+    pass\n",
            "subsequent_changes": "",
            "gold_label": "None",
        },
        {
            "comment_id": "c-3",
            "source": "hunk-level",
            "comment_text": "Please improve readability here.",
            "review_diff": "@@ -9,1 +9,2 @@\n def g():\n+    pass\n",
            "subsequent_changes": "@@ -9,1 +9,3 @@\n def g():\n+    pass\n",
            "gold_label": "General",
        },
    ]
    return write_jsonl(tmp_path / "records.jsonl", rows)


@pytest.fixture
def sample_records():
    return [
        make_record("r-1"),
        make_record("r-2", source="hunk-level", comment_text="This loop leaks the file handle."),
        make_record("r-3", comment_text="LGTM"),
    ]


@pytest.fixture
def make_record_factory():
    """Expose :func:`make_record` to tests that need ad-hoc records."""
    return make_record


@pytest.fixture
def prompts():
    return PromptSet.load(
        PROMPTS_DIR / "stage1.md",
        PROMPTS_DIR / "stage2.md",
        "test-v1",
    )
