"""Tests for the RQ3 feature assembly."""

import numpy as np
import pandas as pd
import pytest

from swep.features import (
    FEATURE_GROUPS,
    GROUP_ALIASES,
    build_feature_matrix,
    group_importance,
    importance_groups,
    map_model,
    topic_columns,
)


def frame(rows=6):
    """A minimal frame with every raw column the builder understands."""
    data = {
        "Comment_ID": ["c-%d" % index for index in range(rows)],
        "Source": ["anc95/ChatGPT-CodeReview", "coderabbitai/ai-pr-reviewer", "Human"] * (rows // 3) + ["Human"] * (rows % 3),
        "Trigger_Mode": ["auto", "manual", "human"] * (rows // 3) + ["human"] * (rows % 3),
        "Model_Configured": ["gpt-4", "gpt-3.5-turbo", "human"] * (rows // 3) + ["human"] * (rows % 3),
        "Repo_Total_File_Size": np.arange(rows, dtype=float) * 100.0,
        "Repo_Total_Issue_Number": np.arange(rows, dtype=float),
        "Repo_Total_NonBot_Contributor_Number": np.arange(rows, dtype=float) + 1,
        "File_Depth": np.arange(rows),
        "Past_Commit_Count": np.arange(rows) * 2,
        "Is_Anonymous": [False] * rows,
        "Is_Bot": [True, False] * (rows // 2) if rows % 2 == 0 else [True] * rows,
        "Commit_Base_Total_Line_Count": np.arange(rows) * 10,
        "Commit_Accumulated_Total_Del_Line_Count": np.arange(rows),
        "File_Add_Line_Count": np.arange(rows) + 3,
        "File_Del_Line_Count": np.arange(rows),
        "File_Base_Line_Count": np.arange(rows) * 5,
        "Comment_Adds": np.arange(rows),
        "Comment_Dels": np.arange(rows),
        "Text_Length": np.arange(rows) * 7 + 5,
        "Has_Inline_Code": [True, False] * (rows // 2) if rows % 2 == 0 else [True] * rows,
        "Has_Multiline_Code": [False] * rows,
        "Code_Text_Ratio": np.linspace(0.0, 0.5, rows),
        "Cumulative_Prior_Text_Length": np.arange(rows) * 3,
        "File_Final_Type": ["programming"] * (rows - 1) + ["documentation"],
        "Cleaned_Body": ["Please rename `foo`."] * rows,
    }
    for index in range(6):
        data["LDA_Topic_Prob_%d" % index] = np.linspace(0, 1, rows) / 6.0
    return pd.DataFrame(data)


class TestAssemble(object):
    def test_default_build_uses_every_group(self):
        matrix = build_feature_matrix(frame(), action_binary=False)
        assert set(matrix.available_groups()) == {"repo", "modification", "textual", "file", "action", "topic"}
        assert set(topic_columns()) <= set(matrix.columns)
        assert "Is_Human" in matrix.columns
        assert "Source_coderabbitai/ai-pr-reviewer" in matrix.columns
        assert matrix.frame.dtypes.unique().tolist() == [np.dtype("float64")]

    def test_one_hot_values_match_the_rows(self):
        matrix = build_feature_matrix(frame(), groups=["action"], action_binary=False)
        assert int(matrix.frame["Is_Human"].sum()) == 2
        assert int(matrix.frame["Is_File_Level_Action"].sum()) == 2
        assert int(matrix.frame["Trigger_auto"].sum()) == 2
        assert int(matrix.frame["Model_gpt-4"].sum()) == 2

    def test_binary_action_encodes_manual_and_gpt4(self):
        matrix = build_feature_matrix(frame(), groups=["action"], action_binary=True)
        assert "Trigger_Is_Manual" in matrix.columns
        assert "Model_Is_GPT4" in matrix.columns
        assert "Trigger_auto" not in matrix.columns
        assert int(matrix.frame["Trigger_Is_Manual"].sum()) == 2

    def test_action_binary_is_detected_from_the_data(self):
        machine_only = frame()
        machine_only["Trigger_Mode"] = "auto"
        machine_only["Model_Configured"] = "gpt-4o"
        matrix = build_feature_matrix(machine_only, groups=["action"])
        assert "Trigger_Is_Manual" in matrix.columns
        assert matrix.notes[0].startswith("action features use binary encoding")

    def test_action_binary_falls_back_to_one_hot(self):
        matrix = build_feature_matrix(frame(), groups=["action"])
        assert "Trigger_auto" in matrix.columns
        assert matrix.notes[0].startswith("action features use one-hot encoding")

    def test_missing_columns_are_reported(self):
        data = frame().drop(columns=["Repo_Total_File_Size"])
        matrix = build_feature_matrix(data)
        assert "Repo_Total_File_Size" in matrix.missing["numeric"]
        assert "Repo_Total_File_Size" not in matrix.columns

    def test_text_features_are_not_derived_by_default(self):
        data = frame().drop(columns=["Text_Length"], errors="ignore")
        matrix = build_feature_matrix(data, groups=["textual"])
        assert "Text_Length" not in matrix.columns
        assert "Code_Total_Length" not in matrix.columns

    def test_derived_text_features_when_requested(self):
        data = frame().drop(columns=["Text_Length"])
        matrix = build_feature_matrix(data, groups=["textual"], derive_text=True)
        assert "Text_Length" in matrix.columns
        assert matrix.frame["Text_Length"].iloc[0] == len("Please rename `foo`.")
        assert any("derived textual features" in note for note in matrix.notes)

    def test_source_alias_selects_the_action_group(self):
        matrix = build_feature_matrix(frame(), groups=["source"])
        assert "Is_Human" in matrix.columns
        assert GROUP_ALIASES["source"] == "action"

    def test_unknown_group_raises(self):
        with pytest.raises(ValueError, match="unknown feature group"):
            build_feature_matrix(frame(), groups=["nope"])

    def test_describe_is_json_ready(self):
        described = build_feature_matrix(frame()).describe()
        assert described["rows"] == 6
        assert described["columns"] == len(described["feature_names"])
        assert set(described["groups"]) == {"repo", "modification", "textual", "file", "action", "topic"}


class TestHelpers(object):
    @pytest.mark.parametrize(
        "value, expected",
        [("gpt-3.5-turbo", "gpt-3.5"), ("gpt-4o-mini", "gpt-4"), ("unknown", "unknown"), ("human", "NA"), (None, "NA")],
    )
    def test_map_model(self, value, expected):
        assert map_model(value) == expected

    def test_importance_groups_fold_topics_into_textual(self):
        groups = importance_groups()
        assert set(groups) == {"repo", "modification", "textual", "source"}
        assert "LDA_Topic_Prob_3" in groups["textual"]
        assert "Source_coderabbitai/ai-pr-reviewer" in groups["source"]

    def test_group_importance_totals(self):
        names = ["Text_Length", "LDA_Topic_Prob_0", "Is_Human", "NotAGroupedFeature"]
        values = [0.5, 0.25, 0.75, 9.0]
        frame = group_importance(names, values)
        rows = frame.set_index("group")
        assert rows.loc["textual", "sum_abs_shap"] == pytest.approx(0.75)
        assert rows.loc["source", "sum_abs_shap"] == pytest.approx(0.75)
        assert "NotAGroupedFeature" not in frame.to_string()
        assert frame["sum_abs_shap"].is_monotonic_decreasing
