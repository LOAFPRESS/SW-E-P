"""Build the 150-comment gold dataset from the Zenodo appendix.

Usage (from the repository root)::

    python scripts/build_gold_dataset.py \
        --zenodo-root "C:/path/to/AIReviewActionAnalysis(Zenodo)" \
        --output data/gold150.jsonl

The script is a thin wrapper around :func:`swep.data.zenodo.build_gold_records`:
it joins the sampled reviews with their human labels, maps the compact label
codes onto the six pipeline classes and writes JSONL plus a provenance file next
to it.  Re-running it is idempotent; the provenance file records the SHA-256 of
every input file so a results run can be traced back to its data (DOM-1.4).
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from swep.data.zenodo import (  # noqa: E402  (path set up above)
    SAMPLES,
    build_gold_records,
    write_jsonl,
    write_provenance,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--zenodo-root",
        default=str(REPO_ROOT.parent / "AIReviewActionAnalysis(Zenodo)"),
        help="extracted Zenodo appendix directory (default: sibling of the repo)",
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "data" / "gold150.jsonl"),
        help="where to write the JSONL dataset",
    )
    parser.add_argument(
        "--sources",
        nargs="*",
        default=None,
        choices=[sample[0] for sample in SAMPLES],
        help="restrict the build to some review granularities",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    records, stats = build_gold_records(args.zenodo_root, sources=args.sources)

    dataset_path = write_jsonl(records, args.output)
    provenance_path = write_provenance(stats, dataset_path.with_suffix(".provenance.json"))

    print("wrote %d record(s) to %s" % (len(records), dataset_path))
    print("provenance: %s" % provenance_path)
    print("per source: %s" % stats["per_source"])
    print("gold labels: %s" % stats["labels"])
    if stats["unlabeled"]:
        print("warning: %d input row(s) had no label" % sum(len(v) for v in stats["unlabeled"].values()))
    if stats["duplicate_comment_ids"]:
        print("warning: %d duplicate comment id(s)" % stats["duplicate_comment_ids"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
