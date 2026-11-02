"""Tests for prompt rendering and version fingerprinting (DOM-1.2)."""

import pytest

from swep.errors import ConfigError
from swep.prompts import PromptSet, load_template
from swep.prompts.builder import MAX_DIFF_CHARS


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
