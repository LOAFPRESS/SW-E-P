"""Tests for the RQ3 driver (loading, experiment, artefacts)."""

import json
import os

import numpy as np
import pandas as pd
import pytest

from swep import rq3


def synthetic_rq3(rows=40, positive_share=0.5):
    """Feature table + labels shaped like the Zenodo package."""
    rng = np.random.RandomState(7)
    labels = np.array([1] * int(rows * positive_share) + [0] * (rows - int(rows * positive_share)))
    rng.shuffle(labels)

    data = {
        "Comment_ID": ["https://api.github.com/repos/demo/repo/pulls/comments/%d" % index for index in range(rows)],
        "Source": (["anc95/ChatGPT-CodeReview", "coderabbitai/ai-pr-reviewer", "Human"] * rows)[:rows],
        "Trigger_Mode": (["auto", "manual", "human"] * rows)[:rows],
        "Model_Configured": (["gpt-4", "gpt-3.5-turbo", "human"] * rows)[:rows],
        "Repo_Total_File_Size": rng.randint(100, 10000, rows),
        "Repo_Total_Issue_Number": rng.randint(0, 200, rows),
        "Repo_Total_NonBot_Contributor_Number": rng.randint(1, 50, rows),
        "File_Depth": rng.randint(1, 6, rows),
        "Past_Commit_Count": rng.randint(0, 500, rows),
        "Is_Anonymous": rng.randint(0, 2, rows).astype(bool),
        "Is_Bot": rng.randint(0, 2, rows).astype(bool),
        "Commit_Base_Total_Line_Count": rng.randint(10, 5000, rows),
        "Commit_Accumulated_Total_Del_Line_Count": rng.randint(0, 400, rows),
        "File_Add_Line_Count": rng.randint(0, 300, rows),
        "File_Del_Line_Count": rng.randint(0, 300, rows),
        "File_Base_Line_Count": rng.randint(1, 2000, rows),
        "Comment_Adds": rng.randint(0, 50, rows),
        "Comment_Dels": rng.randint(0, 50, rows),
        "Text_Length": rng.randint(5, 900, rows),
        "Has_Inline_Code": rng.randint(0, 2, rows).astype(bool),
        "Has_Multiline_Code": rng.randint(0, 2, rows).astype(bool),
        "Code_Text_Ratio": rng.rand(rows),
        "Cumulative_Prior_Text_Length": rng.randint(0, 5000, rows),
        "File_Final_Type": (["programming", "documentation"] * rows)[:rows],
        "Cleaned_Body": ["comment body %d" % index for index in range(rows)],
    }
    for index in range(6):
        data["LDA_Topic_Prob_%d" % index] = rng.dirichlet(np.ones(6), size=rows)[:, index]
    features = pd.DataFrame(data)
    labels_frame = pd.DataFrame({"Comment_ID": features["Comment_ID"], "Change_Label": labels})
    return features, labels_frame


def write_inputs(tmp_path, features, labels, name="features.csv"):
    features_path = os.path.join(str(tmp_path), name)
    labels_path = os.path.join(str(tmp_path), "labels.csv")
    features.to_csv(features_path, index=False)
    labels.to_csv(labels_path, index=False)
    return features_path, labels_path


class TestLoad(object):
    def test_merge_reports_counts(self, tmp_path):
        features, labels = synthetic_rq3()
        features_path, labels_path = write_inputs(tmp_path, features, labels)
        frame, meta = rq3.load_rq3_frame(str(tmp_path), features_path=features_path, labels_path=labels_path)
        assert len(frame) == 40
        assert meta["rows_after_merge"] == 40
        assert meta["positive"] + meta["negative"] == 40
        assert meta["positive_rate"] == pytest.approx(meta["positive"] / 40.0, abs=1e-4)
        assert meta["by_source"]["Human"] == len(frame[frame["Source"] == "Human"])

    def test_unlabeled_rows_are_dropped(self, tmp_path):
        features, labels = synthetic_rq3()
        labels.loc[0, "Change_Label"] = None
        features_path, labels_path = write_inputs(tmp_path, features, labels)
        frame, meta = rq3.load_rq3_frame(str(tmp_path), features_path=features_path, labels_path=labels_path)
        assert len(frame) == 39
        assert meta["unlabeled_rows_dropped"] == 1

    def test_duplicate_comment_ids_are_dropped(self, tmp_path):
        features, labels = synthetic_rq3()
        duplicated = pd.concat([features, features.iloc[[0]]], ignore_index=True)
        duplicated_labels = pd.concat([labels, labels.iloc[[0]]], ignore_index=True)
        features_path, labels_path = write_inputs(tmp_path, duplicated, duplicated_labels)
        frame, meta = rq3.load_rq3_frame(str(tmp_path), features_path=features_path, labels_path=labels_path)
        assert meta["duplicate_rows_dropped"] >= 1
        assert len(frame) == 40
        assert frame["Comment_ID"].is_unique

    def test_unexpected_label_value_raises(self, tmp_path):
        features, labels = synthetic_rq3()
        labels.loc[0, "Change_Label"] = 2
        features_path, labels_path = write_inputs(tmp_path, features, labels)
        with pytest.raises(ValueError, match="unexpected Change_Label"):
            rq3.load_rq3_frame(str(tmp_path), features_path=features_path, labels_path=labels_path)

    def test_missing_input_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="RQ3 input not found"):
            rq3.load_rq3_frame(str(tmp_path))

    def test_missing_label_column_raises(self, tmp_path):
        features, labels = synthetic_rq3()
        labels = labels.drop(columns=["Change_Label"])
        features_path, labels_path = write_inputs(tmp_path, features, labels)
        with pytest.raises(ValueError, match="needs Comment_ID and Change_Label"):
            rq3.load_rq3_frame(str(tmp_path), features_path=features_path, labels_path=labels_path)


class TestExperiment(object):
    def test_cv_only_run(self, tmp_path):
        features, labels = synthetic_rq3()
        features_path, labels_path = write_inputs(tmp_path, features, labels)
        frame, meta = rq3.load_rq3_frame(str(tmp_path), features_path=features_path, labels_path=labels_path)
        report = rq3.run_experiment(frame, n_splits=3, explain=False)
        assert report["mode"] == "all_reviews"
        assert report["rows"] == 40
        assert report["cross_validation"]["n_splits"] == 3
        assert "shap" not in report
        assert report["feature_matrix"]["columns"] > 20

    def test_ai_only_drops_human_rows_and_is_human(self, tmp_path):
        features, labels = synthetic_rq3()
        features_path, labels_path = write_inputs(tmp_path, features, labels)
        frame, _ = rq3.load_rq3_frame(str(tmp_path), features_path=features_path, labels_path=labels_path)
        report = rq3.run_experiment(frame, n_splits=3, ai_only=True, explain=False)
        assert report["mode"] == "ai_only"
        assert report["rows"] == len(frame[frame["Source"] != "Human"])
        assert "Is_Human" not in report["feature_matrix"]["feature_names"]

    def test_shap_section_is_recorded(self, tmp_path):
        features, labels = synthetic_rq3(rows=60)
        features_path, labels_path = write_inputs(tmp_path, features, labels)
        frame, _ = rq3.load_rq3_frame(str(tmp_path), features_path=features_path, labels_path=labels_path)
        report = rq3.run_experiment(frame, n_splits=3, explain=True)
        shap_info = report["shap"]
        assert shap_info["available"] is True
        assert len(shap_info["importance"]) == report["feature_matrix"]["columns"]
        assert shap_info["importance"][0]["mean_abs_shap"] >= shap_info["importance"][-1]["mean_abs_shap"]
        assert shap_info["groups"]
        assert len(shap_info["top_features"]) == min(10, report["feature_matrix"]["columns"])


class TestWriteReport(object):
    def test_writes_json_and_markdown(self, tmp_path):
        features, labels = synthetic_rq3()
        features_path, labels_path = write_inputs(tmp_path, features, labels)
        frame, meta = rq3.load_rq3_frame(str(tmp_path), features_path=features_path, labels_path=labels_path)
        report = rq3.run_experiment(frame, n_splits=3, explain=False)
        output = os.path.join(str(tmp_path), "out")
        written = rq3.write_report(report, output, dataset_meta=meta, plot=False)
        assert len(written) == 2
        with open(os.path.join(output, "rq3_metrics.json"), encoding="utf-8") as handle:
            payload = json.load(handle)
        assert payload["dataset"]["rows_after_merge"] == 40
        assert payload["cross_validation"]["n_splits"] == 3
        with open(os.path.join(output, "rq3_report.md"), encoding="utf-8") as handle:
            markdown = handle.read()
        assert "# RQ3 Random Forest report" in markdown
        assert "Stratified 5-fold metrics" in markdown

    def test_shap_artefacts_when_available(self, tmp_path):
        features, labels = synthetic_rq3(rows=60)
        features_path, labels_path = write_inputs(tmp_path, features, labels)
        frame, meta = rq3.load_rq3_frame(str(tmp_path), features_path=features_path, labels_path=labels_path)
        report = rq3.run_experiment(frame, n_splits=3, explain=True)
        output = os.path.join(str(tmp_path), "out")
        written = rq3.write_report(report, output, dataset_meta=meta, plot=False)
        names = sorted(os.path.basename(path) for path in written)
        assert names == ["rq3_feature_importance.csv", "rq3_group_importance.csv", "rq3_metrics.json", "rq3_report.md"]
        importance = pd.read_csv(os.path.join(output, "rq3_feature_importance.csv"))
        assert {"feature", "mean_abs_shap", "mean_shap"}.issubset(importance.columns)
