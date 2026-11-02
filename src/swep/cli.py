"""Command-line interface for the annotation module.

Usage::

    python run.py annotate --config config/config.yaml --limit 5
    python run.py validate-data --config config/config.yaml
    python run.py annotate --provider openai --limit 20

Exit codes (documented for the integration with ``run.py`` of the whole project):

====  =========================================================
0     run completed (individual record failures are reported)
2     configuration or dataset error
3     stopped because the cost budget was exhausted
4     provider rejected the request (authentication, bad model)
====  =========================================================
"""

import argparse
import shutil
import sys
import time
from pathlib import Path

from .config import Config
from .data import describe_dataset, load_dataset
from .errors import BudgetExceeded, ConfigError, DataValidationError, LLMCallError, SwepError
from .export import (
    compute_stability,
    evaluate_against_gold,
    summarize_run,
    write_annotations_csv,
    write_json,
    write_run_report,
)
from .llm import PriceTable, ResponseCache, build_llm_client
from .logging_utils import JsonlWriter, setup_logger
from .pipeline import AnnotationPipeline, run_fingerprint
from .prompts import PromptSet
from .schema import CSV_COLUMNS

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_CONFIG = 2
EXIT_BUDGET = 3
EXIT_PROVIDER = 4

DEFAULT_COMMAND = "annotate"
KNOWN_COMMANDS = ("annotate", "validate-data")

EPILOG = """examples:
  python run.py validate-data -c config/config.yaml
  python run.py annotate -c config/config.yaml --limit 5 --write-report
  python run.py annotate -c config/config.yaml --provider openai
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="Two-stage LLM annotation of AI code-review comments (SW-E-P, Group 8).",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="swep 0.1.0")
    sub = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", default="config/config.yaml", help="YAML configuration file")
    common.add_argument("--limit", type=int, default=None, help="annotate at most N comments")
    common.add_argument("--provider", choices=["mock", "openai"], default=None, help="override llm.provider")
    common.add_argument("--output-dir", default=None, help="override output.dir")
    common.add_argument("--dataset", default=None, help="override data.path")
    common.add_argument("--no-cache", action="store_true", help="ignore the response cache")
    common.add_argument("--quiet", action="store_true", help="no progress bar")

    annotate = sub.add_parser("annotate", parents=[common], help="run the two-stage annotation")
    annotate.add_argument("--write-report", action="store_true", help="also write a markdown run report")
    annotate.add_argument("--dry-run", action="store_true", help="validate inputs and estimate cost only")
    annotate.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="run the whole batch N times and report label stability (the paper uses 5)",
    )

    sub.add_parser("validate-data", parents=[common], help="load and describe the dataset, no LLM calls")
    return parser


def _apply_overrides(config: Config, args) -> None:
    """Apply CLI overrides on top of the YAML values (documented in --help)."""
    if getattr(args, "provider", None):
        config.raw["llm"]["provider"] = args.provider
    if getattr(args, "limit", None) is not None:
        config.raw["run"]["limit"] = args.limit
    if getattr(args, "output_dir", None):
        config.raw["output"]["dir"] = args.output_dir
    if getattr(args, "dataset", None):
        config.raw["data"]["path"] = args.dataset


def _load_records(config: Config, logger):
    dataset = config.get("data.path", None)
    if not dataset:
        raise ConfigError(
            "no dataset configured: pass --dataset <path> or set data.path in config/config.yaml"
        )
    dataset_path = config.resolve(dataset)
    return load_dataset(
        dataset_path,
        fmt=config.get("data.format", "auto"),
        column_map=config.get("data.column_map", {}),
        limit=config.get("run.limit", None),
        split=config.get("data.split", None),
        logger=logger,
    )


def _cmd_validate_data(config: Config, args) -> int:
    logger = setup_logger(None, level="INFO", stream=not args.quiet)
    records = _load_records(config, logger)
    stats = describe_dataset(records)
    print("dataset: %s" % config.resolve(config.get("data.path")))
    print("records: %d" % stats["count"])
    for source, count in stats["by_source"].items():
        print("  %-12s %d" % (source, count))
    print("with review diff: %d" % stats["with_review_diff"])
    print("with subsequent changes: %d" % stats["with_subsequent_changes"])
    print("with gold label: %d" % stats["with_gold_label"])
    print("synthetic rows: %d" % stats["synthetic"])
    return EXIT_OK


def _cmd_annotate(config: Config, args) -> int:
    output_dir = config.output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = output_dir / "run.log"
    logger = setup_logger(log_file, level=config.get("run.log_level", "INFO"), stream=not args.quiet)

    logger.info("swep annotation start: %s", config.describe())
    logger.info("configuration file: %s", config.path)
    logger.info("output directory: %s", output_dir)

    prompts = PromptSet.load(
        config.resolve(config.get("prompts.stage1")),
        config.resolve(config.get("prompts.stage2")),
        config.get("prompts.version"),
    )
    logger.info("prompts: %s", prompts.describe())

    records = _load_records(config, logger)
    dataset_stats = describe_dataset(records)
    logger.info("dataset: %s", dataset_stats)

    if args.dry_run:
        prices = PriceTable.from_config(config)
        max_output = int(config.get("llm.max_output_tokens"))
        stage1_chars = sum(
            len("".join(message["content"] for message in prompts.stage1_messages(record)))
            for record in records
        )
        average_prompt_tokens = (stage1_chars // max(1, len(records))) // 4
        worst_case = 2 * len(records) * prices.cost(
            config.get("llm.stage2_model"), average_prompt_tokens + 800, max_output
        )
        print("dry run: %d record(s), at most %d LLM calls" % (len(records), 2 * len(records)))
        print("worst-case cost estimate: $%.4f (budget: %s)" % (
            worst_case, config.get("llm.budget.max_usd", None)
        ))
        print("provider=%s stage1=%s stage2=%s" % (
            config.get("llm.provider"), config.get("llm.stage1_model"), config.get("llm.stage2_model")
        ))
        return EXIT_OK

    client = build_llm_client(config)
    repeat = max(1, int(getattr(args, "repeat", 1) or 1))
    cache_enabled = bool(config.get("llm.cache.enabled")) and not args.no_cache
    if repeat > 1:
        # Repeated sampling must not be served from the cache: every repeat
        # would otherwise return the first answer and agreement would be 1.0
        # by construction (DEV-04 in docs/paper-deviations.md).
        cache_enabled = False
    cache = ResponseCache(config.resolve(config.get("llm.cache.path")), enabled=cache_enabled)
    request_log = JsonlWriter(output_dir / config.get("output.requests_jsonl"))
    budget_usd = float(config.get("llm.budget.max_usd", 0.0) or 0.0)
    results = []

    started = time.perf_counter()
    try:
        for attempt in range(repeat):
            if repeat > 1:
                logger.info("repeat %d/%d", attempt + 1, repeat)
            pipeline = AnnotationPipeline(
                config,
                client,
                prompts,
                cache=cache,
                request_log=request_log,
                logger=logger,
                progress=not args.quiet and repeat == 1,
            )
            results.append(pipeline.run(records))
            spent = sum(float(item.stats.cost_usd) for item in results)
            if budget_usd and spent > budget_usd:
                logger.warning(
                    "cumulative cost $%.4f exceeds the budget $%.4f; stopping after %d repeat(s)",
                    spent,
                    budget_usd,
                    len(results),
                )
                break
    except BudgetExceeded as exc:
        logger.error("budget exceeded: %s", exc)
        return EXIT_BUDGET
    except LLMCallError as exc:
        logger.error("provider error: %s", exc)
        return EXIT_PROVIDER
    finally:
        request_log.close()
        cache.close()
        client.close()

    result = results[0]

    csv_path = write_annotations_csv(
        result.annotations, output_dir / config.get("output.annotations_csv")
    )
    logger.info("wrote %s (%d row(s), %d column(s))", csv_path, len(result.annotations), len(CSV_COLUMNS))

    gold = {
        record.comment_id: record.gold_label
        for record in records
        if record.gold_label
    }
    sources = {record.comment_id: record.source for record in records if record.source}
    evaluation = evaluate_against_gold(result.annotations, gold, sources=sources)
    fingerprint = run_fingerprint(config, prompts)
    extra = {
        "evaluation": evaluation,
        "artifacts": {"annotations_csv": str(csv_path)},
    }
    if repeat > 1:
        extra["stability"] = compute_stability(results)
    summary = summarize_run(
        result,
        dataset_stats,
        config,
        prompts,
        fingerprint,
        extra=extra,
    )
    summary["elapsed_wall_s"] = round(time.perf_counter() - started, 2)
    summary_path = write_json(summary, output_dir / config.get("output.summary_json"))
    logger.info("wrote %s", summary_path)

    if args.write_report:
        report_path = write_run_report(summary, output_dir / "run_report.md")
        logger.info("wrote %s", report_path)

    _print_summary(summary, result)
    return EXIT_OK if result.ok else EXIT_PROVIDER


def _print_summary(summary, result) -> None:
    stats = summary["pipeline"]
    print("")
    print("annotated %d record(s): %d ok, %d failed" % (
        stats["processed"], stats["completed"], stats["failed"]
    ))
    print("LLM calls: %d (cache hits %d, retries %d, parse repairs %d)" % (
        stats["llm_calls"], stats["cache_hits"], stats["retries"], stats["parse_retries"]
    ))
    print("tokens: %d input / %d output, cost $%.4f" % (
        stats["input_tokens"], stats["output_tokens"], stats["cost_usd"]
    ))
    print("labels (six classes):")
    for label, count in summary["labels"]["final_six_class"].items():
        print("  %-18s %d" % (label, count))
    print("addressed rate: %.1f%%" % (100.0 * summary["labels"]["addressed_rate"]))
    evaluation = summary.get("evaluation")
    if evaluation:
        print("against gold (n=%d): accuracy %.3f, macro-F1 %.3f" % (
            evaluation["n"],
            evaluation["six_class"]["accuracy"],
            evaluation["six_class"]["macro_f1"],
        ))
        for source, values in (evaluation.get("per_source") or {}).items():
            print("  %-12s n=%d accuracy %.3f macro-F1 %.3f" % (
                source, values["n"], values["accuracy"], values["macro_f1"]
            ))
    stability = summary.get("stability")
    if stability:
        print("stability over %d repeat(s): agreement %.1f%% (%d/%d records)" % (
            stability["repeats"],
            100.0 * stability["agreement_rate"],
            stability["stable_records"],
            stability["comparable_records"],
        ))
    if stats.get("stopped_reason"):
        print("stopped: %s" % stats["stopped_reason"])


def _with_default_command(argv):
    """Allow ``python run.py -c config/config.yaml`` without a subcommand."""
    argv = list(argv)
    if not argv or argv[0] not in KNOWN_COMMANDS + ("-h", "--help", "--version"):
        return [DEFAULT_COMMAND] + argv
    return argv


def main(argv=None) -> int:
    parser = build_parser()
    argv = _with_default_command(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(argv)
    command = args.command or DEFAULT_COMMAND
    if command == "validator":  # pragma: no cover - defensive
        command = "validate-data"

    try:
        config = Config.load(args.config)
    except ConfigError as exc:
        print("configuration error: %s" % exc, file=sys.stderr)
        print("hint: pass -c <path>; the repository ships config/config.yaml (provider: mock, no API key needed)", file=sys.stderr)
        return EXIT_CONFIG
    _apply_overrides(config, args)

    try:
        if command == "validate-data":
            return _cmd_validate_data(config, args)
        return _cmd_annotate(config, args)
    except DataValidationError as exc:
        print("dataset error: %s" % exc, file=sys.stderr)
        return EXIT_CONFIG
    except ConfigError as exc:
        print("configuration error: %s" % exc, file=sys.stderr)
        return EXIT_CONFIG
    except KeyboardInterrupt:
        print("interrupted; partial results are kept in the output directory", file=sys.stderr)
        return EXIT_UNEXPECTED
    except SwepError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return EXIT_UNEXPECTED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
