"""Run the RQ3 Random Forest + SHAP experiment on the Zenodo feature matrix.

This is a thin wrapper around ``swep.rq3``; the same experiment is reachable
through the project's single entry point::

    python run.py rq3
    python run.py rq3 --ai-only --no-shap
    python run.py rq3 --zenodo-root "C:\\path\\to\\AIReviewActionAnalysis(Zenodo)\\address_feature_matrix"

The default input is the 3879-review feature matrix that ships with the Zenodo
package; ``--ai-only`` reproduces the paper's AI-only variant (Human rows
removed, 2990 reviews).
"""

import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from swep import rq3  # noqa: E402


def build_parser():
    return rq3.build_parser(prog="run_rq3.py")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return rq3.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
