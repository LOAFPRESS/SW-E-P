"""Tests for parsing model answers into typed results (REQ-1.15)."""

import pytest

from swep.errors import ParseError
from swep.llm.parsing import extract_json_object, parse_stage1, parse_stage2
from swep.schema import Stage1Label, Stage2Label

VALID_STAGE1 = '{"label": "Valid", "issues": ["validate the extension"], "rationale": "Specific."}'
VALID_STAGE2 = (
    '{"label": "Valid-Fully", "addressed_items": ["validate the extension"],'
    ' "unaddressed_items": [], "rationale": "The check was added."}'
)


class TestJsonExtraction:
    def test_plain_object(self):
        assert extract_json_object('{"a": 1}') == {"a": 1}

    def test_markdown_fenced_object(self):
        text = 'Here you go:\n```json\n{"a": 2}\n```\nDone.'
        assert extract_json_object(text) == {"a": 2}

    def test_unlabelled_fence(self):
        assert extract_json_object('```\n{"a": 3}\n```') == {"a": 3}

    def test_object_followed_by_prose(self):
        assert extract_json_object('{"a": 4} and that is my answer') == {"a": 4}

    def test_braces_inside_strings_do_not_break_parsing(self):
        assert extract_json_object('{"note": "use {braces} carefully"}')["note"] == "use {braces} carefully"

    def test_escaped_quotes_inside_strings(self):
        payload = extract_json_object('{"note": "he said \\"hi\\""}')
        assert payload["note"] == 'he said "hi"'

    def test_no_object_raises_with_a_snippet(self):
        with pytest.raises(ParseError) as excinfo:
            extract_json_object("I cannot answer that.")
        assert "cannot answer" in str(excinfo.value)


class TestStage1Parsing:
    def test_valid_answer(self):
        result = parse_stage1(VALID_STAGE1)
        assert result.label is Stage1Label.VALID
        assert result.issues == ["validate the extension"]
        assert result.is_valid

    def test_label_aliases_are_normalised(self):
        result = parse_stage1('{"label": "general", "rationale": "vague"}')
        assert result.label is Stage1Label.GENERAL

    def test_unknown_label_raises(self):
        with pytest.raises(ParseError) as excinfo:
            parse_stage1('{"label": "Maybe", "rationale": "x"}')
        assert "Maybe" in str(excinfo.value)

    def test_missing_label_raises(self):
        with pytest.raises(ParseError):
            parse_stage1('{"issues": []}')

    def test_valid_without_issues_promotes_the_rationale(self):
        result = parse_stage1(
            '{"label": "Valid", "issues": [], '
            '"rationale": "The reviewer asks to validate the file extension before reading it."}'
        )
        assert result.label is Stage1Label.VALID
        assert len(result.issues) == 1
        assert "extension" in result.issues[0]
        assert result.warnings

    def test_valid_without_issues_or_rationale_is_demoted(self):
        result = parse_stage1('{"label": "Valid", "issues": [], "rationale": "yes"}')
        assert result.label is Stage1Label.GENERAL
        assert result.warnings

    def test_none_with_issues_has_the_checklist_cleared(self):
        result = parse_stage1('{"label": "None", "issues": ["something"], "rationale": "praise"}')
        assert result.label is Stage1Label.NONE
        assert result.issues == []
        assert result.warnings

    def test_issue_list_from_multiline_string(self):
        result = parse_stage1(
            '{"label": "Valid", "issues": "- fix the null check\\n- add a test", "rationale": "x y z"}'
        )
        assert result.issues == ["fix the null check", "add a test"]

    def test_duplicate_and_empty_issues_are_removed(self):
        result = parse_stage1(
            '{"label": "Valid", "issues": ["a", "a", "", "none"], "rationale": "x y z"}'
        )
        assert result.issues == ["a"]


class TestStage2Parsing:
    def test_fully_addressed(self):
        result = parse_stage2(VALID_STAGE2)
        assert result.label is Stage2Label.FULLY
        assert result.addressed_items == ["validate the extension"]

    def test_partially_addressed(self):
        result = parse_stage2(
            '{"label": "Valid-Partially", "addressed_items": ["a"], "unaddressed_items": ["b"]}'
        )
        assert result.label is Stage2Label.PARTIALLY

    def test_inconsistent_lists_are_flagged_but_kept(self):
        result = parse_stage2(
            '{"label": "Valid-Fully", "addressed_items": [], "unaddressed_items": ["b"]}'
        )
        assert result.label is Stage2Label.FULLY
        assert result.warnings

    def test_unknown_label_raises(self):
        with pytest.raises(ParseError):
            parse_stage2('{"label": "Maybe"}')
