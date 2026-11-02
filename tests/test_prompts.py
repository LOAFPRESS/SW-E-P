"""Tests for prompt rendering and version fingerprinting (DOM-1.2)."""

import json

import pytest

from swep.errors import ConfigError
from swep.prompts import PromptSet, load_template
from swep.prompts.builder import MAX_DIFF_CHARS, describe_code_change

from conftest import PROMPTS_DIR, make_record


class TestRendering:
    def test_stage1_embeds_comment_and_diff(self, prompts, sample_records):
        messages = prompts.stage1_messages(sample_records[0])
        assert messages[0]["role"] == "system"
        user = messages[1]["content"]
        assert sample_records[0].comment_text in user
        assert sample_records[0].review_diff in user
        assert "$comment_text" not in user
        assert "$review_diff" not in user

    def test_stage1_includes_annotation_context(self, prompts, sample_records):
        user = prompts.stage1_messages(sample_records[0])[1]["content"]
        assert "file-level" in user
        assert "demo/repo" in user

    def test_stage2_renders_the_checklist_as_bullets(self, prompts, sample_records):
        messages = prompts.stage2_messages(sample_records[0], ["close the handle", "add a test"])
        user = messages[1]["content"]
        assert "- close the handle" in user
        assert "- add a test" in user

    def test_stage2_handles_an_empty_checklist(self, prompts, sample_records):
        user = prompts.stage2_messages(sample_records[0], [])[1]["content"]
        assert "(empty)" in user

    def test_missing_optional_fields_are_rendered_as_placeholders(self, prompts, make_record_factory):
        record = make_record_factory()
        record.repo = None
        user = prompts.stage1_messages(record)[1]["content"]
        assert "(not available)" in user

    def test_long_diffs_are_truncated(self, prompts, make_record_factory):
        record = make_record_factory()
        record.review_diff = "+ line\n" * (MAX_DIFF_CHARS // 2)
        user = prompts.stage1_messages(record)[1]["content"]
        assert "[truncated]" in user
        assert len(user) < len(record.review_diff)

    def test_unknown_placeholder_is_reported(self, tmp_path):
        path = tmp_path / "bad.md"
        path.write_text("hello $unknown_field", encoding="utf-8")
        template = load_template("bad", path)
        with pytest.raises(ConfigError) as excinfo:
            template.render({"comment_text": "x"})
        assert "unknown_field" in str(excinfo.value)


class TestFingerprint:
    def test_fingerprint_is_stable_for_identical_templates(self, prompts):
        assert prompts.fingerprint == prompts.fingerprint

    def test_fingerprint_changes_when_a_template_changes(self, tmp_path):
        first = tmp_path / "stage1.md"
        second = tmp_path / "stage1b.md"
        first.write_text("Stage 1: $comment_text", encoding="utf-8")
        second.write_text("Stage 1 (edited): $comment_text", encoding="utf-8")
        stage2 = tmp_path / "stage2.md"
        stage2.write_text("Stage 2: $comment_text", encoding="utf-8")

        original = PromptSet.load(first, stage2, "v1")
        edited = PromptSet.load(second, stage2, "v1")
        assert original.fingerprint != edited.fingerprint

    def test_version_is_part_of_the_fingerprint(self, tmp_path):
        stage1 = tmp_path / "stage1.md"
        stage2 = tmp_path / "stage2.md"
        stage1.write_text("$comment_text", encoding="utf-8")
        stage2.write_text("$comment_text", encoding="utf-8")
        assert (
            PromptSet.load(stage1, stage2, "v1").fingerprint
            != PromptSet.load(stage1, stage2, "v2").fingerprint
        )

    def test_describe_mentions_both_digests(self, prompts):
        description = prompts.describe()
        assert prompts.stage1.digest in description
        assert prompts.stage2.digest in description

    def test_missing_template_file(self, tmp_path):
        with pytest.raises(ConfigError):
            load_template("missing", tmp_path / "nope.md")


class TestAppendixPrompts:
    """The verbatim appendix templates ask for text, not JSON."""

    def _paper_set(self, output_format="text"):
        return PromptSet.load(
            PROMPTS_DIR / "stage1_v2_original.md",
            PROMPTS_DIR / "stage2_v2_original.md",
            "v2-paper-2026-11",
            output_format=output_format,
        )

    def test_values_are_inlined_as_json_literals(self):
        prompts = self._paper_set()
        record = make_record(comment_text='Use "quotes" and\nnewlines carefully.')
        content = prompts.stage1_messages(record)[1]["content"]
        assert json.dumps(record.comment_text, ensure_ascii=False) in content
        assert "$review_comment" not in content

    def test_stage1_asks_for_the_appendix_output(self):
        prompts = self._paper_set()
        content = prompts.stage1_messages(make_record())[1]["content"]
        assert "List the identified issues or suggestions" in content

    def test_stage2_renders_the_issue_checklist(self):
        prompts = self._paper_set()
        record = make_record()
        content = prompts.stage2_messages(record, ["validate the extension", "handle empty files"])[1]["content"]
        assert "validate the extension" in content
        assert "handle empty files" in content

    def test_stage2_renders_the_subsequent_changes_paragraph(self):
        prompts = self._paper_set()
        content = prompts.stage2_messages(make_record(), ["one"])[1]["content"]
        assert "Subsequent Code Changes: The cumulative code changes are:" in content
        assert "@@ -1,3 +1,5 @@" in content

    def test_text_format_uses_the_text_system_prompt(self):
        assert self._paper_set("text").system_prompt != self._paper_set("json").system_prompt

    def test_unknown_format_is_rejected(self):
        with pytest.raises(ConfigError) as excinfo:
            self._paper_set("xml")
        assert "prompts.format" in str(excinfo.value)

    def test_fingerprint_includes_the_format_independent_templates(self):
        assert self._paper_set().fingerprint.startswith("v2-paper-2026-11:")


class TestDescribeCodeChange:
    def test_no_change(self):
        record = make_record(subsequent_changes="")
        assert "No change happened" in describe_code_change(record)

    def test_deleted_file(self):
        record = make_record(subsequent_changes="File_Deleted")
        assert "was deleted after the review" in describe_code_change(record)

    def test_renamed_file(self):
        record = make_record(
            reviewed_path="pkg/old.py",
            new_path="pkg/new.py",
            subsequent_changes="@@ -1 +1 @@\n-a\n+b\n",
        )
        text = describe_code_change(record)
        assert "renamed to pkg/new.py" in text
        assert "+b" in text

    def test_normal_change(self):
        record = make_record(reviewed_path="pkg/mod.py", new_path="pkg/mod.py")
        text = describe_code_change(record)
        assert "renamed" not in text
        assert "+    return None" in text
