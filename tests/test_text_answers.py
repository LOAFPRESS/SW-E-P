"""Tests for the appendix's plain-text answer format (``format: text``).

The paper's appendix prompts do not ask for JSON: they end with
``Output: List ... and make the final classification.`` and the reference
implementation parses a ``Classification:`` line.  These tests pin that format,
including the short-circuit answers and the "earliest match after the marker"
rule that ``analyze_addressed_status.py`` uses.
"""

import pytest

from swep.errors import ParseError
from swep.llm.parsing import (
    parse_stage1_text,
    parse_stage2_text,
    split_items,
    stage1_parser,
    stage2_parser,
)
from swep.schema import Stage1Label, Stage2Label

STAGE1_VALID = """Issues or Suggestions:
- The `parse_config` function should validate the file extension before reading it.
- Missing error handling when the file is empty.

Classification: Contain Valid Issues Or Suggestions
"""

STAGE1_GENERAL = """Issues or Suggestions:
- Consider improving the readability of this file.

Classification: Only Contain General Issues Or Suggestions
"""

STAGE1_NONE = """Issues or Suggestions:
- None

Classification: Not Contain Any Issues Or Suggestions
"""

STAGE2_FULLY = """Analysis details:

- Addressed Items:
- The `parse_config` function now validates the file extension.
- Empty files are rejected with a clear error.

- Unaddressed Items:
- None

Classification: Fully Addressed
"""

STAGE2_PARTLY = """Analysis details:

- Addressed Items:
- The extension check was added.

- Unaddressed Items:
- Empty files still silently return None.

Classification: Partly Addressed
"""

STAGE2_UNADDRESSED = """Analysis details:

- Addressed Items:
- None

- Unaddressed Items:
- The extension check is still missing.

Classification: Not Addressed
"""

STAGE2_UNCERTAIN = """Analysis details:

- Addressed Items:
- None

- Unaddressed Items:
- It is unclear whether the change landed before the merge.

Classification: Not Enough Information
"""


class TestStage1Text:
    def test_valid_answer(self):
        result = parse_stage1_text(STAGE1_VALID)
        assert result.label is Stage1Label.VALID
        assert result.is_valid
        assert len(result.issues) == 2
        assert "parse_config" in result.issues[0]

    def test_general_answer(self):
        result = parse_stage1_text(STAGE1_GENERAL)
        assert result.label is Stage1Label.GENERAL
        assert result.issues == []

    def test_none_answer(self):
        result = parse_stage1_text(STAGE1_NONE)
        assert result.label is Stage1Label.NONE
        assert result.issues == []

    def test_short_circuit_answer(self):
        assert parse_stage1_text("Not contain any items.").label is Stage1Label.NONE
        assert parse_stage1_text("Not contain specific items.").label is Stage1Label.GENERAL

    def test_json_answer_is_still_accepted(self):
        result = parse_stage1_text('{"label": "Valid", "issues": ["add a check"]}')
        assert result.label is Stage1Label.VALID
        assert result.issues == ["add a check"]

    def test_missing_classification_raises(self):
        with pytest.raises(ParseError) as excinfo:
            parse_stage1_text("Issues or Suggestions:\n- something vague\n")
        assert "Classification" in str(excinfo.value)

    def test_empty_answer_raises(self):
        with pytest.raises(ParseError) as excinfo:
            parse_stage1_text("   \n")
        assert "empty" in str(excinfo.value)

    def test_bullets_and_numbering_are_stripped(self):
        text = (
            "Issues or Suggestions:\n"
            "1. Rename the parameter.\n"
            "2) Document the return value.\n"
            "\nClassification: Contain Valid Issues Or Suggestions\n"
        )
        assert parse_stage1_text(text).issues == [
            "Rename the parameter.",
            "Document the return value.",
        ]


class TestStage2Text:
    def test_fully_addressed(self):
        result = parse_stage2_text(STAGE2_FULLY)
        assert result.label is Stage2Label.FULLY
        assert len(result.addressed_items) == 2
        assert result.unaddressed_items == []

    def test_partly_addressed(self):
        result = parse_stage2_text(STAGE2_PARTLY)
        assert result.label is Stage2Label.PARTIALLY
        assert result.addressed_items
        assert result.unaddressed_items

    def test_not_addressed(self):
        result = parse_stage2_text(STAGE2_UNADDRESSED)
        assert result.label is Stage2Label.UNADDRESSED
        assert result.unaddressed_items

    def test_not_enough_information(self):
        assert parse_stage2_text(STAGE2_UNCERTAIN).label is Stage2Label.UNCERTAIN

    def test_short_circuit_answer(self):
        answer = "No change happened; the comment remains unaddressed."
        assert parse_stage2_text(answer).label is Stage2Label.UNADDRESSED

    def test_earliest_match_wins(self):
        # "Not Addressed" appears before "Fully Addressed": the appendix takes
        # the earliest match, and so do we.
        text = "Analysis details:\nClassification: Not Addressed, not Fully Addressed"
        assert parse_stage2_text(text).label is Stage2Label.UNADDRESSED

    def test_missing_classification_raises(self):
        with pytest.raises(ParseError):
            parse_stage2_text("Analysis details:\n- Addressed Items:\n- something")

    def test_empty_answer_raises(self):
        with pytest.raises(ParseError):
            parse_stage2_text("")

    def test_json_answer_is_still_accepted(self):
        result = parse_stage2_text('{"label": "Valid-Uncertain", "rationale": "unclear"}')
        assert result.label is Stage2Label.UNCERTAIN


class TestHelpers:
    def test_split_items_filters_empties_and_duplicates(self):
        block = "\n- one\n- one\n- None\n- n/a\n- (empty)\n- two\n"
        assert split_items(block) == ["one", "two"]

    def test_split_items_collapses_whitespace(self):
        assert split_items("-   spaced    out   item") == ["spaced out item"]

    def test_parser_factories(self):
        assert stage1_parser("text") is parse_stage1_text
        assert stage1_parser("json") is not parse_stage1_text
        assert stage2_parser("text") is parse_stage2_text
