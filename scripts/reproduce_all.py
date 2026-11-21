#!/usr/bin/env python
"""Reproduce every number the report quotes, in one run.

Three modes, from cheapest to most expensive:

    python scripts/reproduce_all.py                # assemble from existing artefacts
    python scripts/reproduce_all.py --recompute    # + rerun the random forest (minutes)
    python scripts/reproduce_all.py --rerun-llm    # + rerun both annotation batches (money)

The default mode only reads what is already in ``artifacts/``: it re-runs the
deterministic, sub-minute steps (dataset validation, the paper comparison, the
prompt A/B comparison, the four-claims check) and copies the numbers of the
expensive steps (the two LLM batches, RQ3) from their JSON files. Nothing is
sent to a provider, so the default mode and ``--recompute`` cost nothing.

Everything it writes goes to ``artifacts/reproduction/``:

    manifest.json   inputs with sha256, versions, the numbers themselves
    report.md       the same numbers as Markdown, ready to paste in the report

``--rerun-llm`` needs ``DEEPSEEK_API_KEY``; the two batches cost about 0.6 USD
and take about 40 minutes together.
"""

import argparse
import datetime
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO / "artifacts"
OUT = ARTIFACTS / "reproduction"

# where the canonical numbers of each step live
GOLD = REPO / "data" / "gold150.jsonl"
FEATURES = (
    REPO.parent
    / "AIReviewActionAnalysis(Zenodo)"
    / "address_feature_matrix"
    / "_selected_reviews_with_features"
    / "reviews_contains_valid_by_LLM_lda_topics_selected.csv"
)
RUN_V2 = ARTIFACTS / "deepseek-paper"
RUN_V21 = ARTIFACTS / "deepseek-v21"
RQ3_ALL = ARTIFACTS / "rq3" / "all_reviews"
RQ3_AI = ARTIFACTS / "rq3" / "ai_only"
RQ3_CONCLUSIONS = ARTIFACTS / "rq3" / "conclusions.json"
AB_JSON = ARTIFACTS / "rq2-ab.json"

PAPER = {  # Table VII of the paper, accuracy / macro-F1
    "stage1": (0.945, 0.908),
    "stage2": (0.918, 0.885),
    "six_class": (0.861, 0.746),
    "binary": (0.915, 0.898),
}


def python():
    return sys.executable


def run(args, allow_failure=False):
    """Run a child process in the repository and return its stdout."""
    env = dict(os.environ)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    proc = subprocess.run(
        [python()] + args,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if proc.returncode != 0 and not allow_failure:
        sys.stderr.write(proc.stdout or "")
        sys.stderr.write(proc.stderr or "")
        raise SystemExit("%s failed with exit code %d" % (" ".join(args), proc.returncode))
    return proc.stdout.strip()


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_load(path):
    with open(str(path), encoding="utf-8") as handle:
        return json.load(handle)


def git_commit():
    """The commit the artefacts were produced from (empty if git is unavailable)."""
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO),
                              capture_output=True, text=True)
    except OSError:
        return "unknown"
    return proc.stdout.strip() if proc.returncode == 0 else "unknown"


def versions():
    import platform

    try:
        import numpy
        import pandas

        out = {
            "python": platform.python_version(),
            "numpy": numpy.__version__,
            "pandas": pandas.__version__,
        }
    except Exception:  # pragma: no cover - only informational
        out = {"python": platform.python_version()}
    for name in ("sklearn", "shap"):
        try:
            module = __import__(name)
            out[name] = module.__version__
        except Exception:
            continue
    return out


def pct(value):
    return "-" if value is None else "%.1f %%" % (value * 100.0)


def step_validate():
    return run(["run.py", "validate-data", "-c", "config/config.gold150.yaml", "--quiet"])


def step_ab(json_path):
    table = run([
        "scripts/compare_runs.py",
        str(RUN_V2 / "annotations.csv"),
        str(RUN_V21 / "annotations.csv"),
        "--labels", "v2", "v2.1",
        "--json", str(json_path),
    ])
    return table, json_load(json_path)


def step_paper(csv_path):
    """The table printed by compare_with_paper, minus its one-line dict dump."""
    text = run(["scripts/compare_with_paper.py", str(csv_path)])
    return "\n".join(line for line in text.splitlines()
                     if not line.startswith("binary detail:"))


def step_conclusions(json_path):
    run([
        "scripts/rq3_conclusions.py",
        "--json", str(json_path),
    ])
    return json_load(json_path)


def step_rq3(recompute):
    """The random forest is the only slow but free step."""
    if recompute:
        run(["run.py", "rq3", "--output", str(OUT / "rq3-all")])
        run(["run.py", "rq3", "--ai-only", "--output", str(OUT / "rq3-ai")])
        return OUT / "rq3-all" / "rq3_metrics.json", OUT / "rq3-ai" / "rq3_metrics.json"
    return RQ3_ALL / "rq3_metrics.json", RQ3_AI / "rq3_metrics.json"


def step_rerun_llm():
    run(["run.py", "annotate", "-c", "config/config.deepseek.yaml", "--write-report"])
    run(["run.py", "annotate", "-c", "config/config.deepseek-v21.yaml", "--write-report"])


def step_sensitivity(json_path):
    """Label sensitivity (DEV-12): two tiny random forests, a few seconds."""
    run([
        "scripts/rq3_label_sensitivity.py",
        "--json", str(json_path),
    ])
    return json_load(json_path)


def markdown(payload):
    lines = []
    add = lines.append

    add("# Reproduction bundle")
    add("")
    add("Generated %s from commit `%s`." % (payload["generated_at"], payload["commit"][:9]))
    add("")
    add("## Inputs")
    add("")
    add("| Input | Rows | sha256 |")
    add("| --- | --- | --- |")
    for item in payload["inputs"]:
        add("| `%s` | %s | `%s` |" % (item["name"], item["rows"], item["sha256"][:16]))
    add("")
    add("Versions: %s." % ", ".join("%s %s" % (k, v) for k, v in sorted(payload["versions"].items())))
    add("")

    add("## RQ2 — dataset validation")
    add("")
    add("```")
    add(payload["validate"].strip())
    add("```")
    add("")

    add("## RQ2 — the two annotation runs against the paper (accuracy / macro-F1)")
    add("")
    add("| View | v2 | v2.1 | Paper |")
    add("| --- | --- | --- | --- |")
    for view in ("stage1", "stage2", "six_class", "binary"):
        v2 = payload["ab"]["metrics"]["v2"].get(view) or {}
        v21 = payload["ab"]["metrics"]["v2.1"].get(view) or {}
        paper = PAPER[view]
        add("| %s | %s / %s | %s / %s | %s / %s |" % (
            view,
            pct(v2.get("accuracy")), pct(v2.get("macro_f1")),
            pct(v21.get("accuracy")), pct(v21.get("macro_f1")),
            pct(paper[0]), pct(paper[1]),
        ))
    add("")
    agreement = payload["ab"]["agreement"]
    add("Agreement between the two prompts: %d of %d records (%.1f %%), %d of them changed "
        "their Stage-1 label." % (
            agreement["shared"] - agreement["changed"], agreement["shared"],
            100.0 * agreement["agreement_rate"], agreement["stage1_changed"]))
    add("")
    add("### Per source, v2.1")
    add("")
    add("```")
    add(payload["paper_table"].strip())
    add("```")
    add("")

    add("## RQ3 — random forest and SHAP")
    add("")
    add("| Run | Rows | Features | Accuracy | Macro-F1 |")
    add("| --- | --- | --- | --- | --- |")
    for name, metrics in (("all reviews", payload["rq3_all"]), ("AI only", payload["rq3_ai"])):
        cv = metrics["cross_validation"]
        add("| %s | %d | %d | %.4f | %.4f |" % (
            name, metrics["rows"], cv["n_features"],
            cv["accuracy_mean"], cv["macro_f1_mean"]))
    add("")
    for name, metrics in (("all reviews", payload["rq3_all"]), ("AI only", payload["rq3_ai"])):
        top = metrics["shap"]["importance"][:10] if metrics["shap"].get("importance") else []
        add("**%s — top features:** %s" % (
            name, ", ".join("%s (%s)" % (row["feature"], row["mean_abs_shap"])
                            for row in top[:10])))
        add("")

    add("## RQ3 — the four practical claims")
    add("")
    claims = payload["conclusions"]["conclusions"]

    def claim_table(block, title):
        overall_row = block.get("overall") or {}
        if overall_row:
            add("**%s** — %d of %d adopted (%.1f %%)." % (
                title, overall_row["addressed"], overall_row["rows"],
                100.0 * overall_row["rate"]))
            add("")
        add("| Claim | Group | Rows | Adopted | Rate |")
        add("| --- | --- | --- | --- | --- |")
        for key in ("comment_length", "code_snippets", "trigger", "granularity"):
            for label, row in _claim_rows(block.get(key)):
                add("| %s | %s | %d | %d | %.1f %% |" % (
                    key, label, row.get("rows", 0), row.get("addressed", 0),
                    100.0 * row.get("rate", 0.0)))
        add("")

    claim_table(claims, "All 3,879 reviews")
    if claims.get("ai_only"):
        claim_table(claims["ai_only"], "AI only, Human removed")

    sensitivity = payload.get("sensitivity") or {}
    if sensitivity.get("runs"):
        add("## RQ3 — label sensitivity (DEV-12)")
        add("")
        agree = sensitivity["agreement"]
        add("%d comments are labelled by both us and the paper. The two binary label sets agree "
            "on %.1f %% of them (Cohen's kappa %.3f)." % (
                agree["n"], 100.0 * agree["agreement"], agree["kappa"]))
        add("")
        add("| Labels | Rows | Accuracy | Macro-F1 |")
        add("| --- | --- | --- | --- |")
        for result in sensitivity["runs"]:
            add("| %s | %d | %.4f ± %.4f | %.4f ± %.4f |" % (
                result["labels"], result["rows"], result["accuracy"], result["accuracy_std"],
                result["macro_f1"], result["macro_f1_std"]))
        add("")
        for shift in sensitivity.get("rank_shifts") or []:
            if shift.get("mean_shift") is None:
                continue
            add("- SHAP ranking, %s vs %s: mean absolute shift %.2f over %d shared features."
                % (shift["first"], shift["second"], shift["mean_shift"], shift["n"]))
        add("")

    add("## Where each number is explained")
    add("")
    add("- `docs/rq2-results.md` — the two annotation runs, per source, error analysis")
    add("- `docs/rq3-rf-shap.md` — protocol, comparison with the paper, SHAP tables")
    add("- `docs/rq3-label-sensitivity.md` — what changes when the labels come from our run")
    add("- `docs/rq3-conclusions.md` — the four claims, with the Human confound")
    add("- `docs/paper-deviations.md` — DEV-01 … DEV-13, every difference from the paper")
    add("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--recompute", action="store_true",
                        help="rerun the random forest instead of reading its JSON")
    parser.add_argument("--rerun-llm", action="store_true",
                        help="rerun both annotation batches (needs DEEPSEEK_API_KEY)")
    args = parser.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)

    if args.rerun_llm:
        print("rerunning both annotation batches ...")
        step_rerun_llm()

    print("validating the gold dataset ...")
    validate = step_validate()

    print("comparing the two prompts ...")
    ab_table, ab = step_ab(OUT / "rq2-ab.json")

    print("comparing against the paper ...")
    paper_table = step_paper(RUN_V21 / "annotations.csv")

    print("checking the four claims ...")
    conclusions = step_conclusions(OUT / "conclusions.json")

    print("collecting RQ3 metrics ...")
    rq3_all_path, rq3_ai_path = step_rq3(args.recompute)

    print("checking the label sensitivity ...")
    sensitivity = step_sensitivity(OUT / "label-sensitivity.json")

    payload = {
        "generated_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "commit": git_commit(),
        "versions": versions(),
        "inputs": [
            {"name": "data/gold150.jsonl", "rows": _count_rows(GOLD) + 1,
             "sha256": sha256(GOLD)},
            {"name": "address_feature_matrix/.../lda_topics_selected.csv",
             "rows": _count_rows(FEATURES), "sha256": sha256(FEATURES)},
        ],
        "validate": validate,
        "ab": ab,
        "paper_table": paper_table,
        "rq3_all": json_load(rq3_all_path),
        "rq3_ai": json_load(rq3_ai_path),
        "conclusions": conclusions,
        "sensitivity": sensitivity,
        "artifacts": {
            "report": str(OUT / "report.md"),
            "manifest": str(OUT / "manifest.json"),
            "rq3_all": str(rq3_all_path),
            "rq3_ai": str(rq3_ai_path),
            "ab": str(OUT / "rq2-ab.json"),
            "conclusions": str(OUT / "conclusions.json"),
            "label_sensitivity": str(OUT / "label-sensitivity.json"),
        },
    }

    (OUT / "manifest.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
    (OUT / "report.md").write_text(markdown(payload), encoding="utf-8")

    print("")
    print(ab_table)
    print("")
    print("wrote %s" % (OUT / "report.md"))
    print("wrote %s" % (OUT / "manifest.json"))
    return 0


def _claim_rows(block):
    """Yield (label, row) for both a list of buckets and a dict keyed by group."""
    if isinstance(block, list):
        for row in block:
            if isinstance(row, dict) and "rows" in row:
                yield row.get("bucket") or row.get("label") or "?", row
    elif isinstance(block, dict):
        for label, row in block.items():
            if isinstance(row, dict) and "rows" in row:
                yield label, row


def _count_rows(path):
    """Rows of a CSV, counted with the csv module so quoted newlines do not inflate it."""
    import csv
    with open(str(path), newline="", encoding="utf-8-sig") as handle:
        return max(sum(1 for _ in csv.reader(handle)) - 1, 0)


if __name__ == "__main__":
    sys.exit(main())



