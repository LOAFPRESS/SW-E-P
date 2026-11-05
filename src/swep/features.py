"""Feature assembly for the RQ3 Random Forest experiment (member C).

This module rebuilds the feature matrix that the paper's appendix uses in
``address_feature_matrix/build_features.py`` (``assemble_feature_matrix`` plus
``FEATURE_GROUP_MAPPING``).  The published matrix is shipped with the Zenodo
package, but the module is written to work from the raw per-review table as
well so that the feature set can be extended or re-derived.

Two deliberate differences from the appendix code:

* missing columns are reported instead of silently dropped, so every run can
  state exactly which of the paper's features were unavailable;
* the same feature matrix is used for every cross-validation fold (the
  appendix also builds the matrix once, before splitting), which keeps the
  one-hot columns stable across folds.

The grouped feature names follow ``FEATURE_GROUP_MAPPING`` so that the group
level SHAP summary can be compared with the paper's Figure/Table.
"""

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

FEATURE_GROUPS: Dict[str, Tuple[str, ...]] = {
    "repo": (
        "Repo_Total_File_Number",
        "Repo_Total_File_Size",
        "Repo_Total_PR_Number",
        "Repo_Total_Issue_Number",
        "Repo_Total_NonBot_Contributor_Number",
    ),
    "modification": (
        "Author_Is_Anonymous",
        "Author_Is_Bot",
        "Author_Past_Commit_Count",
        "Commit_Accumulated_Changed_File_Count",
        "Commit_Accumulated_Total_Change_Line_Count",
        "Commit_Accumulated_Total_Add_Line_Count",
        "Commit_Accumulated_Total_Del_Line_Count",
        "Commit_Base_Total_Line_Count",
        "Is_Programming_File",
        "File_Depth",
        "File_Change_Line_Count",
        "File_Add_Line_Count",
        "File_Del_Line_Count",
        "File_Base_Line_Count",
        "Comment_Adds",
        "Comment_Dels",
        "Comment_Changes",
    ),
    "textual": (
        "Text_Length",
        "Has_Inline_Code",
        "Has_Multiline_Code",
        "Code_Total_Length",
        "Code_Text_Ratio",
        "Cumulative_Prior_Text_Length",
        "Timeline_Index",
        "Thread_Companion_Count",
    ),
    "file": (
        "Is_Programming_File",
        "File_Depth",
    ),
    "action": (
        "Is_Human",
        "Is_File_Level_Action",
        "Trigger_auto",
        "Trigger_manual",
        "Trigger_Is_Manual",
        "Model_gpt-3.5",
        "Model_gpt-4",
        "Model_Is_GPT4",
        "Source_aidar-freeed/ai-codereviewer",
        "Source_anc95/ChatGPT-CodeReview",
        "Source_coderabbitai/ai-pr-reviewer",
        "Source_mattzcarey/code-review-gpt",
    ),
}

# Selectable feature groups; ``source`` is an accepted alias of ``action``.
GROUP_ALIASES: Dict[str, str] = {"source": "action"}

TOPIC_NUMBER = 6
TOPIC_GROUP = "topic"

SOURCE_VALUES: Tuple[str, ...] = (
    "aidar-freeed/ai-codereviewer",
    "anc95/ChatGPT-CodeReview",
    "coderabbitai/ai-pr-reviewer",
    "mattzcarey/code-review-gpt",
    "Human",
)
FILE_LEVEL_SOURCES: Tuple[str, ...] = (
    "anc95/ChatGPT-CodeReview",
    "mattzcarey/code-review-gpt",
)


def topic_columns(topic_number: int = TOPIC_NUMBER) -> List[str]:
    """Names of the LDA topic probability columns."""
    return ["LDA_Topic_Prob_%d" % index for index in range(topic_number)]


def _group_columns() -> Dict[str, List[str]]:
    groups = {name: list(columns) for name, columns in FEATURE_GROUPS.items()}
    groups[TOPIC_GROUP] = topic_columns()
    return groups


def importance_groups(topic_number: int = TOPIC_NUMBER) -> Dict[str, List[str]]:
    """Feature grouping used for the group-level SHAP summary.

    This follows the appendix's ``FEATURE_GROUP_MAPPING``: the LDA probabilities
    are part of the textual group and every action column (including the
    per-source dummies) is part of the source group.
    """
    return {
        "repo": list(FEATURE_GROUPS["repo"]),
        "modification": list(FEATURE_GROUPS["modification"]),
        "textual": list(FEATURE_GROUPS["textual"]) + topic_columns(topic_number) + ["Timeline_Index", "Thread_Companion_Count"],
        "source": list(FEATURE_GROUPS["action"]),
    }


def map_model(value) -> str:
    """Collapse a model string to ``gpt-3.5`` / ``gpt-4`` / ``unknown`` / ``NA``."""
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("gpt-3.5"):
            return "gpt-3.5"
        if text.startswith("gpt-4"):
            return "gpt-4"
        if text == "unknown":
            return "unknown"
    return "NA"


def _as_frame(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    if "Cleaned_Body" not in frame.columns:
        frame["Cleaned_Body"] = ""
    if "Source" not in frame.columns:
        raise KeyError("the feature table needs a 'Source' column")
    return frame


def _derive_text_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Fill the textual columns that can be recomputed from the comment body."""
    body = frame["Cleaned_Body"].fillna("").astype(str)
    derived = pd.DataFrame(index=frame.index)
    if "Text_Length" not in frame.columns:
        derived["Text_Length"] = body.str.len()
    if "Has_Inline_Code" not in frame.columns:
        derived["Has_Inline_Code"] = body.str.contains("`").astype(int)
    if "Has_Multiline_Code" not in frame.columns:
        derived["Has_Multiline_Code"] = body.str.contains("```").astype(int)
    if "Code_Total_Length" not in frame.columns:
        inline = body.str.findall(r"`([^`]*)`")
        derived["Code_Total_Length"] = inline.apply(lambda parts: sum(len(p) for p in parts))
    return derived


def _numeric_part(frame: pd.DataFrame, columns: Sequence[str], missing: Dict[str, List[str]]) -> Optional[pd.DataFrame]:
    present = [column for column in columns if column in frame.columns]
    absent = [column for column in columns if column not in frame.columns]
    if absent:
        missing["numeric"] = missing.get("numeric", []) + absent
    if not present:
        return None
    block = frame[present].apply(pd.to_numeric, errors="coerce").fillna(0)
    return block


def _action_features(frame: pd.DataFrame, binary: bool) -> pd.DataFrame:
    trigger = frame["Trigger_Mode"].fillna("NA").astype(str) if "Trigger_Mode" in frame.columns else pd.Series("NA", index=frame.index)
    model = frame["Model_Configured"].apply(map_model) if "Model_Configured" in frame.columns else pd.Series("NA", index=frame.index)
    source = frame["Source"].astype(str)

    parts = []
    if binary:
        parts.append((trigger == "manual").astype(int).to_frame(name="Trigger_Is_Manual"))
        parts.append((model == "gpt-4").astype(int).to_frame(name="Model_Is_GPT4"))
    else:
        for value in ("auto", "manual"):
            parts.append((trigger == value).astype(int).to_frame(name="Trigger_%s" % value))
        for value in ("gpt-3.5", "gpt-4"):
            parts.append((model == value).astype(int).to_frame(name="Model_%s" % value))

    parts.append((source == "Human").astype(int).to_frame(name="Is_Human"))
    parts.append(source.isin(FILE_LEVEL_SOURCES).astype(int).to_frame(name="Is_File_Level_Action"))
    for value in SOURCE_VALUES:
        if value == "Human":
            continue
        parts.append((source == value).astype(int).to_frame(name="Source_%s" % value))
    return pd.concat(parts, axis=1)


class FeatureMatrix(object):
    """A built feature matrix plus the bookkeeping needed for reporting."""

    def __init__(self, frame: pd.DataFrame, groups: Dict[str, List[str]], missing: Dict[str, List[str]], notes: List[str]):
        self.frame = frame
        self.groups = groups
        self.missing = missing
        self.notes = notes

    @property
    def columns(self) -> List[str]:
        return list(self.frame.columns)

    @property
    def values(self) -> np.ndarray:
        return self.frame.values

    def available_groups(self) -> List[str]:
        return [group for group, columns in self.groups.items() if columns]

    def drop_columns(self, columns: Sequence[str]) -> "FeatureMatrix":
        """Return a copy without ``columns`` (groups are updated accordingly)."""
        drop = [column for column in columns if column in self.frame.columns]
        if not drop:
            return self
        frame = self.frame.drop(columns=drop)
        groups = {group: [column for column in members if column in frame.columns] for group, members in self.groups.items()}
        notes = list(self.notes) + ["dropped column(s): %s" % ", ".join(drop)]
        return FeatureMatrix(frame, groups, self.missing, notes)

    def describe(self) -> Dict[str, object]:
        """A JSON-serialisable summary of what was built."""
        return {
            "rows": int(self.frame.shape[0]),
            "columns": int(self.frame.shape[1]),
            "feature_names": self.columns,
            "groups": {group: list(columns) for group, columns in self.groups.items()},
            "missing": {key: list(value) for key, value in self.missing.items()},
            "notes": list(self.notes),
        }


def build_feature_matrix(
    df: pd.DataFrame,
    groups: Optional[Iterable[str]] = None,
    action_binary: Optional[bool] = None,
    topic_number: int = TOPIC_NUMBER,
    derive_text: bool = False,
) -> FeatureMatrix:
    """Assemble the structured feature matrix used by the Random Forest.

    ``groups`` defaults to every group in the paper's configuration.  When it
    contains ``"action"`` and ``action_binary`` is not given, binary encoding is
    used only if the data actually supports it (``Trigger_Mode`` limited to
    auto/manual and ``Model_Configured`` limited to gpt-3.5/gpt-4), which mirrors
    the guard in the appendix ``__main__`` block.

    ``derive_text`` recomputes the textual columns from ``Cleaned_Body`` when the
    table does not carry them.  It is off by default: the paper's feature set is
    always used as published, so an approximation is only added when the caller
    explicitly asks for it (and the run then reports the extra column).
    """
    frame = _as_frame(df)
    wanted = list(groups) if groups is not None else ["repo", "modification", "textual", "file", "action", "topic"]
    wanted = [GROUP_ALIASES.get(name, name) for name in wanted]
    all_columns = _group_columns()
    unknown = [group for group in wanted if group not in all_columns]
    if unknown:
        raise ValueError("unknown feature group(s): %s (known: %s)" % (", ".join(unknown), ", ".join(sorted(all_columns))))

    if action_binary is None:
        trigger_ok = True
        if "Trigger_Mode" in frame.columns:
            values = set(frame["Trigger_Mode"].dropna().astype(str))
            trigger_ok = values <= {"auto", "manual"}
        model_ok = True
        if "Model_Configured" in frame.columns:
            mapped = set(frame["Model_Configured"].apply(map_model))
            model_ok = (mapped - {"NA", "unknown"}) <= {"gpt-3.5", "gpt-4"}
        action_binary = bool(trigger_ok and model_ok)

    missing: Dict[str, List[str]] = {}
    notes: List[str] = []
    parts: List[pd.DataFrame] = []

    if "repo" in wanted:
        block = _numeric_part(frame, FEATURE_GROUPS["repo"], missing)
        if block is not None:
            parts.append(block)

    if "modification" in wanted:
        derived = []
        for source, target in (("Is_Anonymous", "Author_Is_Anonymous"), ("Is_Bot", "Author_Is_Bot"), ("Past_Commit_Count", "Author_Past_Commit_Count")):
            if source in frame.columns:
                derived.append((frame[source].astype(int) if source != "Past_Commit_Count" else pd.to_numeric(frame[source], errors="coerce").fillna(0).astype(int)).to_frame(name=target))
            else:
                missing.setdefault("numeric", []).append(source)
        modification_columns = [column for column in FEATURE_GROUPS["modification"] if column not in {"Author_Is_Anonymous", "Author_Is_Bot", "Author_Past_Commit_Count", "Is_Programming_File", "File_Depth"}]
        block = _numeric_part(frame, modification_columns, missing)
        if derived:
            parts.append(pd.concat(derived, axis=1))
        if block is not None:
            parts.append(block)

    if "file" in wanted or "modification" in wanted:
        file_parts = []
        if "File_Final_Type" in frame.columns:
            file_parts.append((frame["File_Final_Type"] == "programming").astype(int).to_frame(name="Is_Programming_File"))
        else:
            missing.setdefault("numeric", []).append("File_Final_Type")
        if "File_Depth" in frame.columns:
            file_parts.append(pd.to_numeric(frame["File_Depth"], errors="coerce").fillna(0).astype(int).to_frame(name="File_Depth"))
        else:
            missing.setdefault("numeric", []).append("File_Depth")
        if file_parts:
            parts.append(pd.concat(file_parts, axis=1))

    if "textual" in wanted:
        textual = [column for column in FEATURE_GROUPS["textual"] if column not in {"Is_Programming_File", "File_Depth"}]
        block = _numeric_part(frame, textual, missing)
        if block is not None:
            parts.append(block)
        if derive_text:
            derived_text = _derive_text_features(frame)
            if not derived_text.empty:
                parts.append(derived_text)
                notes.append("derived textual features from Cleaned_Body: %s" % ", ".join(derived_text.columns))

    if "action" in wanted:
        action = _action_features(frame, bool(action_binary))
        if action_binary:
            notes.append("action features use binary encoding (Trigger_Is_Manual, Model_Is_GPT4)")
        else:
            notes.append("action features use one-hot encoding")
        parts.append(action)

    if "topic" in wanted:
        block = _numeric_part(frame, topic_columns(topic_number), missing)
        if block is not None:
            parts.append(block)

    if not parts:
        raise ValueError("no feature group produced any column; check the input table")

    matrix = pd.concat(parts, axis=1)
    matrix = matrix.loc[:, ~matrix.columns.duplicated()]

    # Recompute the achieved group membership from the final column order.
    achieved: Dict[str, List[str]] = {}
    for group in wanted:
        wanted_columns = all_columns[group]
        achieved[group] = [column for column in matrix.columns if column in wanted_columns]

    unique_missing = {key: sorted(set(value)) for key, value in missing.items()}
    return FeatureMatrix(matrix.astype(float), achieved, unique_missing, notes)


def group_importance(feature_names: Sequence[str], values: Sequence[float]) -> pd.DataFrame:
    """Aggregate per-feature importance into the paper's feature groups."""
    lookup: Dict[str, List[str]] = {}
    for group, columns in importance_groups().items():
        for column in columns:
            lookup.setdefault(column, []).append(group)

    totals: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    for name, value in zip(feature_names, values):
        for group in lookup.get(name, []):
            totals[group] = totals.get(group, 0.0) + float(value)
            counts[group] = counts.get(group, 0) + 1

    rows = []
    for group in sorted(totals):
        rows.append({"group": group, "mean_abs_shap": totals[group] / max(counts[group], 1), "sum_abs_shap": totals[group], "features": counts[group]})
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame = frame.sort_values("sum_abs_shap", ascending=False).reset_index(drop=True)
    return frame
