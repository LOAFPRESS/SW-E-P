"""Descriptive check of the paper's four RQ3 conclusions (W7, supplement for Member A).

The paper closes RQ3 with four practical conclusions:

1. concise review comments are adopted more often;
2. comments that contain code snippets are adopted more often;
3. manually triggered actions are adopted more often;
4. hunk-level (patch-level) reviews are adopted more often than file-level ones.

This script does not re-train anything; it reports the empirical addressed rate
(``Change_Label``) for each of those conditions on the 3879-review modelling set
that ships with the Zenodo package, so that the report can say whether the
conclusions hold in *this* dataset.

Usage::

    .\\.venv\\Scripts\\python.exe scripts\\rq3_conclusions.py
    .\\.venv\\Scripts\\python.exe scripts\\rq3_conclusions.py --json artifacts\\rq3\\conclusions.json
"""

import argparse
import json
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from swep import rq3  # noqa: E402

FILE_LEVEL_SOURCES = ("anc95/ChatGPT-CodeReview", "mattzcarey/code-review-gpt")
LENGTH_BUCKETS = (120, 240, 480)  # characters of the cleaned comment body


def _rate(frame, mask):
    subset = frame[mask]
    total = int(len(subset))
    if not total:
        return {"rows": 0, "addressed": 0, "rate": None}
    addressed = int(subset[rq3.LABEL_COLUMN].sum())
    return {"rows": total, "addressed": addressed, "rate": addressed / float(total)}


def _bucket_label(index):
    return ("<= %d chars" % LENGTH_BUCKETS[0],
            "%d-%d chars" % (LENGTH_BUCKETS[0], LENGTH_BUCKETS[1]),
            "%d-%d chars" % (LENGTH_BUCKETS[1], LENGTH_BUCKETS[2]),
            "> %d chars" % LENGTH_BUCKETS[2])[index]


def analyse(frame):
    body = frame["Cleaned_Body"].fillna("").astype(str)
    length = body.str.len()
    buckets = [length <= LENGTH_BUCKETS[0]]
    for low, high in zip(LENGTH_BUCKETS, LENGTH_BUCKETS[1:]):
        buckets.append((length > low) & (length <= high))
    buckets.append(length > LENGTH_BUCKETS[-1])

    result = {
        "overall": _rate(frame, frame[rq3.LABEL_COLUMN] >= 0),
        "comment_length": [
            dict(bucket=_bucket_label(index), **_rate(frame, mask)) for index, mask in enumerate(buckets)
        ],
        "code_snippets": {
            "has_inline_code": _rate(frame, frame["Has_Inline_Code"].astype(bool)),
            "no_inline_code": _rate(frame, ~frame["Has_Inline_Code"].astype(bool)),
            "has_multiline_code": _rate(frame, frame["Has_Multiline_Code"].astype(bool)),
            "no_multiline_code": _rate(frame, ~frame["Has_Multiline_Code"].astype(bool)),
        },
        "trigger": {
            "auto": _rate(frame, frame["Trigger_Mode"] == "auto"),
            "manual": _rate(frame, frame["Trigger_Mode"] == "manual"),
            "human": _rate(frame, frame["Trigger_Mode"] == "human"),
        },
        "granularity": {
            "file-level": _rate(frame, frame["Source"].isin(FILE_LEVEL_SOURCES)),
            "hunk-level": _rate(frame, ~frame["Source"].isin(FILE_LEVEL_SOURCES) & (frame["Source"] != "Human")),
            "human": _rate(frame, frame["Source"] == "Human"),
        },
    }
    # Human reviews are both far longer and far more often addressed than bot
    # reviews, so they are an obvious confounder for every comparison above.
    # The paper's conclusions are about AI reviews, hence the second view.
    ai_only = frame[frame["Source"] != "Human"].reset_index(drop=True)
    ai_body = ai_only["Cleaned_Body"].fillna("").astype(str)
    ai_length = ai_body.str.len()
    result["ai_only"] = {
        "overall": _rate(ai_only, ai_only[rq3.LABEL_COLUMN] >= 0),
        "comment_length": [
            dict(
                bucket=_bucket_label(index),
                **_rate(
                    ai_only,
                    [
                        ai_length <= LENGTH_BUCKETS[0],
                        *[(ai_length > low) & (ai_length <= high) for low, high in zip(LENGTH_BUCKETS, LENGTH_BUCKETS[1:])],
                        ai_length > LENGTH_BUCKETS[-1],
                    ][index],
                ),
            )
            for index in range(len(LENGTH_BUCKETS) + 1)
        ],
        "code_snippets": {
            "has_inline_code": _rate(ai_only, ai_only["Has_Inline_Code"].astype(bool)),
            "no_inline_code": _rate(ai_only, ~ai_only["Has_Inline_Code"].astype(bool)),
            "has_multiline_code": _rate(ai_only, ai_only["Has_Multiline_Code"].astype(bool)),
            "no_multiline_code": _rate(ai_only, ~ai_only["Has_Multiline_Code"].astype(bool)),
        },
        "trigger": {
            "auto": _rate(ai_only, ai_only["Trigger_Mode"] == "auto"),
            "manual": _rate(ai_only, ai_only["Trigger_Mode"] == "manual"),
        },
        "granularity": {
            "file-level": _rate(ai_only, ai_only["Source"].isin(FILE_LEVEL_SOURCES)),
            "hunk-level": _rate(ai_only, ~ai_only["Source"].isin(FILE_LEVEL_SOURCES)),
        },
    }
    return result


def _line(name, stats):
    if not stats["rows"]:
        return "- %s: no rows" % name
    return "- %s: %d/%d = %.1f%%" % (name, stats["addressed"], stats["rows"], 100.0 * stats["rate"])


def render(result):
    lines = ["# RQ3 practical conclusions, checked on the 3879-review modelling set", ""]
    lines.append("Overall addressed rate: %d/%d = %.1f%%" % (
        result["overall"]["addressed"], result["overall"]["rows"], 100.0 * result["overall"]["rate"]))
    lines.append("")

    sections = (
        ("1. Concise comments are adopted more often", "comment_length"),
        ("2. Comments with code snippets are adopted more often", "code_snippets"),
        ("3. Manually triggered actions are adopted more often", "trigger"),
        ("4. Hunk-level reviews are adopted more often than file-level ones", "granularity"),
    )
    for title, key in sections:
        lines.append("## " + title)
        lines.append("")
        lines.append("All reviews:")
        block = result[key]
        if key == "comment_length":
            for entry in block:
                lines.append(_line(entry["bucket"], entry))
        else:
            for name, stats in block.items():
                lines.append(_line(name, stats))
        lines.append("")
        lines.append("AI reviews only (Human rows removed):")
        ai = result["ai_only"]
        lines.append("Overall: %d/%d = %.1f%%" % (
            ai["overall"]["addressed"], ai["overall"]["rows"], 100.0 * ai["overall"]["rate"]))
        ai_block = ai[key]
        if key == "comment_length":
            for entry in ai_block:
                lines.append(_line(entry["bucket"], entry))
        else:
            for name, stats in ai_block.items():
                lines.append(_line(name, stats))
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zenodo-root", default=rq3.default_zenodo_root())
    parser.add_argument("--features", default=None)
    parser.add_argument("--labels", default=None)
    parser.add_argument("--json", default=None, help="write the raw numbers to this JSON file")
    args = parser.parse_args(argv)

    frame, meta = rq3.load_rq3_frame(args.zenodo_root, features_path=args.features, labels_path=args.labels)
    result = analyse(frame)
    print(render(result))
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump({"meta": meta, "conclusions": result}, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        print("wrote %s" % os.path.relpath(args.json, REPO_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
