"""Run the RQ3 Random Forest + SHAP experiment on the Zenodo feature matrix.

Usage (from the repository root, with the project virtualenv):

    .\\.venv\\Scripts\\python.exe scripts\\run_rq3.py
    .\\.venv\\Scripts\\python.exe scripts\\run_rq3.py --ai-only --no-shap
    .\\.venv\\Scripts\\python.exe scripts\\run_rq3.py --zenodo-root "C:\\path\\to\\AIReviewActionAnalysis(Zenodo)"

The default input is the 3879-review feature matrix that ships with the Zenodo
package; ``--ai-only`` reproduces the paper's AI-only variant (Human rows
removed, 2990 reviews).
"""

import argparse
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from swep import rq3  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_rq3",
        description="Stratified 5-fold Random Forest + SHAP on the RQ3 feature matrix.",
    )
    parser.add_argument(
        "--zenodo-root",
        default=os.path.join(os.path.dirname(REPO_ROOT), "AIReviewActionAnalysis(Zenodo)", "address_feature_matrix"),
        help="address_feature_matrix directory of the Zenodo package",
    )
    parser.add_argument("--features", default=None, help="override the feature CSV path")
    parser.add_argument("--labels", default=None, help="override the label CSV path")
    parser.add_argument("--output", default=os.path.join(REPO_ROOT, "artifacts", "rq3"), help="artefact directory")
    parser.add_argument("--groups", default=None, help="comma separated feature groups (default: all)")
    parser.add_argument("--ai-only", action="store_true", help="drop Human reviews (paper's AI-only variant)")
    parser.add_argument("--n-splits", type=int, default=5, help="number of CV folds (default: 5)")
    parser.add_argument("--random-state", type=int, default=42, help="random seed (default: 42)")
    parser.add_argument("--n-estimators", type=int, default=None, help="override the number of trees")
    parser.add_argument("--action-binary", dest="action_binary", action="store_true", default=None, help="force binary action features")
    parser.add_argument("--no-action-binary", dest="action_binary", action="store_false", help="force one-hot action features")
    parser.add_argument("--no-shap", action="store_true", help="skip the SHAP analysis (CV metrics only)")
    parser.add_argument("--no-plot", action="store_true", help="skip the PNG figures")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    groups = [part.strip() for part in args.groups.split(",")] if args.groups else None

    frame, meta = rq3.load_rq3_frame(args.zenodo_root, features_path=args.features, labels_path=args.labels)
    print("rows: %d (positive %d, %.2f%%)" % (meta["rows_after_merge"], meta["positive"], meta["positive_rate"] * 100))
    if meta["unlabeled_rows_dropped"]:
        print("dropped %d unlabeled row(s)" % meta["unlabeled_rows_dropped"])

    report = rq3.run_experiment(
        frame,
        groups=groups,
        action_binary=args.action_binary,
        n_splits=args.n_splits,
        random_state=args.random_state,
        ai_only=args.ai_only,
        explain=not args.no_shap,
        n_estimators=args.n_estimators,
    )

    cv = report["cross_validation"]
    print("analysed rows: %d (mode %s)" % (report["rows"], report["mode"]))
    print(
        "5-fold: accuracy %.4f (+/- %.4f) | macro F1 %.4f (+/- %.4f) | %d features"
        % (cv["accuracy_mean"], cv["accuracy_std"], cv["macro_f1_mean"], cv["macro_f1_std"], cv["n_features"])
    )
    shap_info = report.get("shap") or {}
    if shap_info.get("available"):
        print("top SHAP features: %s" % ", ".join(shap_info["top_features"]))
    elif shap_info:
        print("SHAP unavailable: %s" % shap_info.get("error"))

    written = rq3.write_report(report, args.output, dataset_meta=meta, plot=not args.no_plot)
    for path in written:
        print("wrote %s" % os.path.relpath(path, REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
