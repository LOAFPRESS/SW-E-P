"""The two-stage annotation pipeline.

For every review comment:

1. **Stage-1 (validity).**  Ask the Stage-1 model whether the comment contains a
   valid issue and, if so, extract the issue checklist (``None`` / ``General`` /
   ``Valid``).
2. **Stage-2 (adoption).**  Only for ``Valid`` comments: give the model the
   Stage-1 checklist, the code at review time and the *subsequent* modifications,
   and ask which items were adopted (``Valid-Uncertain`` / ``Valid-Unaddressed``
   / ``Valid-Partially`` / ``Valid-Fully``).

Cross-cutting behaviour, each tied to a requirement:

========================================  ====================================
Behaviour                                 Requirement
========================================  ====================================
persistent response cache                 REQ-1.17 (Could)
retry with exponential back-off           REQ-1.7
per-call token/cost log (``requests``)    REQ-1.7
cost budget, graceful stop                REQ-1.16 (Could)
one bad record does not kill the run      REQ-1.15
fixed output schema                       REQ-1.8
prompt version recorded per row           DOM-1.2
========================================  ====================================
"""

import hashlib
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .errors import BudgetExceeded, LLMCallError, ParseError, SwepError
from .llm import PriceTable, ResponseCache, RetryPolicy, call_with_retry
from .llm.base import LLMClient, LLMResponse
from .llm.parsing import parse_stage1, parse_stage2
from .logging_utils import JsonlWriter, get_logger
from .prompts import PromptSet
from .schema import (
    AnnotationRecord,
    ReviewRecord,
    Stage1Label,
    Stage2Label,
    final_label_for,
)


@dataclass
class PipelineStats:
    """Counters accumulated during one run."""

    processed: int = 0
    completed: int = 0
    failed: int = 0
    stage2_calls: int = 0
    llm_calls: int = 0
    cache_hits: int = 0
    retries: int = 0
    parse_retries: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_s: float = 0.0
    stopped_reason: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "processed": self.processed,
            "completed": self.completed,
            "failed": self.failed,
            "stage2_calls": self.stage2_calls,
            "llm_calls": self.llm_calls,
            "cache_hits": self.cache_hits,
            "retries": self.retries,
            "parse_retries": self.parse_retries,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "duration_s": round(self.duration_s, 2),
            "stopped_reason": self.stopped_reason,
        }


@dataclass
class PipelineResult:
    """Everything one run produced."""

    annotations: List[AnnotationRecord] = field(default_factory=list)
    stats: PipelineStats = field(default_factory=PipelineStats)
    prompt_fingerprint: str = ""

    @property
    def ok(self) -> bool:
        return self.stats.stopped_reason in ("", "completed")


class AnnotationPipeline:
    """Runs Stage-1 + Stage-2 over a list of :class:`ReviewRecord`."""

    def __init__(
        self,
        config,
        client: LLMClient,
        prompts: PromptSet,
        cache: Optional[ResponseCache] = None,
        request_log: Optional[JsonlWriter] = None,
        logger=None,
        progress: bool = True,
    ):
        self.config = config
        self.client = client
        self.prompts = prompts
        self.cache = cache
        self.request_log = request_log
        self.log = logger or get_logger()
        self.progress = progress

        self.retry_policy = RetryPolicy.from_config(config)
        self.prices = PriceTable.from_config(config)
        self.temperature = float(config.get("llm.temperature"))
        self.max_output_tokens = int(config.get("llm.max_output_tokens"))
        self.model_stage1 = str(config.get("llm.stage1_model"))
        self.model_stage2 = str(config.get("llm.stage2_model"))
        self.max_parse_retries = int(config.get("llm.max_parse_retries", 2))
        self.abort_on_record_error = bool(config.get("run.abort_on_record_error", False))
        budget = config.get("llm.budget.max_usd", None)
        self.budget_usd: Optional[float] = float(budget) if budget is not None else None

        self.stats = PipelineStats()
        self._spent = 0.0

    # ------------------------------------------------------------------ run
    def run(self, records: List[ReviewRecord]) -> PipelineResult:
        """Annotate every record, resilient to per-record failures."""
        started = time.perf_counter()
        annotations: List[AnnotationRecord] = []
        iterator = records
        if self.progress:
            iterator = self._progress(records)

        stop_reason = "completed"
        for record in iterator:
            try:
                annotation = self.annotate_record(record)
            except BudgetExceeded as exc:
                self.log.error("stopping: %s", exc)
                stop_reason = "budget_exceeded"
                break
            except LLMCallError as exc:
                if not exc.retryable:
                    self.log.error("stopping: provider rejected the request: %s", exc)
                    stop_reason = "provider_error"
                    break
                raise
            except SwepError as exc:
                if self.abort_on_record_error:
                    raise
                self.log.error("record %s failed: %s", record.comment_id, exc)
                annotation = self._failed(record, str(exc))
            except Exception as exc:  # noqa: BLE001 - one record must not kill the batch
                if self.abort_on_record_error:
                    raise
                self.log.exception("record %s failed unexpectedly", record.comment_id)
                annotation = self._failed(record, "unexpected error: %s" % exc)

            annotations.append(annotation)
            self.stats.processed += 1
            if annotation.error:
                self.stats.failed += 1
            else:
                self.stats.completed += 1

        self.stats.duration_s = time.perf_counter() - started
        self.stats.stopped_reason = stop_reason
        self._log_totals()
        return PipelineResult(
            annotations=annotations,
            stats=self.stats,
            prompt_fingerprint=self.prompts.fingerprint,
        )

    # --------------------------------------------------------------- single
    def annotate_record(self, record: ReviewRecord) -> AnnotationRecord:
        """Annotate one comment through both stages."""
        annotation = AnnotationRecord(
            comment_id=record.comment_id,
            source=record.source,
            model_stage1=self.model_stage1,
            prompt_version=self.prompts.version,
        )
        warnings: List[str] = []

        stage1_messages = self.prompts.stage1_messages(record)
        stage1_response = self._call(stage1_messages, self.model_stage1, "stage1", record)
        self._account(annotation, stage1_response)

        stage1 = self._parse_with_repair(
            stage1_messages, stage1_response, "stage1", record, annotation
        )
        annotation.stage1_label = stage1.label.value
        annotation.stage1_issues = stage1.issues
        annotation.stage1_rationale = stage1.rationale
        warnings.extend(stage1.warnings)
        for warning in warnings:
            self.log.warning("record %s: %s", record.comment_id, warning)

        if stage1.label is Stage1Label.VALID:
            self.stats.stage2_calls += 1
            annotation.model_stage2 = self.model_stage2
            stage2_messages = self.prompts.stage2_messages(record, stage1.issues)
            stage2_response = self._call(
                stage2_messages,
                self.model_stage2,
                "stage2",
                record,
                issues=stage1.issues,
            )
            self._account(annotation, stage2_response)
            stage2 = self._parse_with_repair(
                stage2_messages,
                stage2_response,
                "stage2",
                record,
                annotation,
                issues=stage1.issues,
            )
            annotation.stage2_label = stage2.label.value
            annotation.addressed_items = stage2.addressed_items
            annotation.unaddressed_items = stage2.unaddressed_items
            annotation.stage2_rationale = stage2.rationale
            for warning in stage2.warnings:
                self.log.warning("record %s: %s", record.comment_id, warning)
        else:
            # No Stage-2 call: keep an explicit empty string so the CSV and the
            # in-memory record agree (None vs "" has bitten us before).
            annotation.stage2_label = ""

        annotation.final_label = final_label_for(annotation.stage1_label, annotation.stage2_label)
        return annotation

    # ----------------------------------------------------------- LLM access
    def _call(
        self,
        messages: List[dict],
        model: str,
        stage: str,
        record: ReviewRecord,
        issues: Optional[List[str]] = None,
    ) -> LLMResponse:
        """One logical call: cache lookup, budget guard, retry, audit log."""
        cache_key = ResponseCache.make_key(model, self.temperature, self.max_output_tokens, messages)
        if self.cache is not None:
            hit = self.cache.get(cache_key)
            if hit is not None:
                self.stats.cache_hits += 1
                response = LLMResponse(
                    text=hit.get("text", ""),
                    model=model,
                    prompt_tokens=int(hit.get("prompt_tokens", 0)),
                    completion_tokens=int(hit.get("completion_tokens", 0)),
                    latency_ms=float(hit.get("latency_ms", 0.0)),
                    cached=True,
                    request_id=hit.get("request_id", "cache"),
                    finish_reason=hit.get("finish_reason", ""),
                )
                self._log_request(record, stage, response, attempts=0, cost=0.0)
                return response

        estimated = self._estimate_cost(messages, model)
        if self.budget_usd is not None and self._spent + estimated > self.budget_usd:
            raise BudgetExceeded(
                "estimated next call ($%.4f) would exceed the configured budget "
                "of $%.2f (already spent $%.4f)"
                % (estimated, self.budget_usd, self._spent)
            )

        attempts = {"count": 0}

        def attempt() -> LLMResponse:
            attempts["count"] += 1
            self.stats.llm_calls += 1
            return self.client.complete(
                messages,
                model,
                temperature=self.temperature,
                max_output_tokens=self.max_output_tokens,
                context={"stage": stage, "record": record, "issues": issues or []},
            )

        def on_retry(attempt_no, exc, delay):
            self.stats.retries += 1

        response = call_with_retry(
            attempt,
            self.retry_policy,
            is_retryable=lambda exc: isinstance(exc, LLMCallError) and exc.retryable,
            on_retry=on_retry,
        )

        cost = self.prices.cost(model, response.prompt_tokens, response.completion_tokens)
        self._spent += cost
        self.stats.input_tokens += response.prompt_tokens
        self.stats.output_tokens += response.completion_tokens
        self.stats.cost_usd += cost

        if self.cache is not None:
            self.cache.put(
                cache_key,
                model,
                {
                    "text": response.text,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                    "latency_ms": response.latency_ms,
                    "request_id": response.request_id,
                    "finish_reason": response.finish_reason,
                },
            )
        self._log_request(record, stage, response, attempts=attempts["count"], cost=cost)
        return response

    def _parse_with_repair(
        self,
        messages: List[dict],
        response: LLMResponse,
        stage: str,
        record: ReviewRecord,
        annotation: AnnotationRecord,
        issues: Optional[List[str]] = None,
    ):
        """Parse an answer, asking the model to repair malformed JSON if needed."""
        parser = parse_stage1 if stage == "stage1" else parse_stage2
        current = response
        last_error: Optional[ParseError] = None
        for attempt_index in range(self.max_parse_retries + 1):
            try:
                return parser(current.text)
            except ParseError as exc:
                last_error = exc
                if attempt_index >= self.max_parse_retries:
                    break
                self.stats.parse_retries += 1
                self.log.warning(
                    "record %s: %s answer unparsable (%s); asking for a repair",
                    record.comment_id,
                    stage,
                    exc,
                )
                repair_messages = list(messages) + [
                    {"role": "assistant", "content": current.text[:2000]},
                    {
                        "role": "user",
                        "content": (
                            "That answer could not be parsed: %s. Reply again with a "
                            "single JSON object that follows the required schema and "
                            "contains no other text." % exc
                        ),
                    },
                ]
                model = self.model_stage1 if stage == "stage1" else self.model_stage2
                current = self._call(repair_messages, model, stage + "-repair", record, issues=issues)
                self._account(annotation, current)
        raise ParseError("%s answer unparsable after repair: %s" % (stage, last_error))

    # --------------------------------------------------------------- helpers
    def _estimate_cost(self, messages: List[dict], model: str) -> float:
        """Upper bound of the next call's cost, used for the budget guard."""
        prompt_chars = sum(len(message.get("content", "")) for message in messages)
        prompt_tokens = prompt_chars // 4 + 1
        return self.prices.cost(model, prompt_tokens, self.max_output_tokens)

    def _account(self, annotation: AnnotationRecord, response: LLMResponse):
        annotation.input_tokens += response.prompt_tokens
        annotation.output_tokens += response.completion_tokens
        annotation.latency_ms += response.latency_ms
        annotation.attempts += 1
        if response.cached:
            annotation.cached_calls += 1
        annotation.cost_usd = self.prices.cost(
            response.model, annotation.input_tokens, annotation.output_tokens
        )

    def _log_request(self, record: ReviewRecord, stage: str, response: LLMResponse, attempts: int, cost: float):
        if self.request_log is None:
            return
        self.request_log.write(
            {
                "run": self.config.get("run.name"),
                "comment_id": record.comment_id,
                "stage": stage,
                "model": response.model,
                "prompt_tokens": response.prompt_tokens,
                "completion_tokens": response.completion_tokens,
                "cost_usd": round(cost, 6),
                "latency_ms": round(response.latency_ms, 1),
                "cached": response.cached,
                "attempts": attempts,
                "request_id": response.request_id,
                "prompt_version": self.prompts.version,
            }
        )

    def _failed(self, record: ReviewRecord, message: str) -> AnnotationRecord:
        annotation = AnnotationRecord(
            comment_id=record.comment_id,
            source=record.source,
            model_stage1=self.model_stage1,
            prompt_version=self.prompts.version,
            error=message[:500],
        )
        return annotation

    def _progress(self, records: List[ReviewRecord]):
        try:
            from tqdm import tqdm

            return tqdm(records, desc="annotate", unit="comment", dynamic_ncols=True)
        except Exception:  # noqa: BLE001 - optional dependency
            return records

    def _log_totals(self):
        self.log.info(
            "finished: %d record(s), %d failed, %d LLM call(s), %d cache hit(s), "
            "%d retry(ies), %d parse repair(s), %.0f input / %.0f output tokens, $%.4f",
            self.stats.processed,
            self.stats.failed,
            self.stats.llm_calls,
            self.stats.cache_hits,
            self.stats.retries,
            self.stats.parse_retries,
            self.stats.input_tokens,
            self.stats.output_tokens,
            self.stats.cost_usd,
        )


def run_fingerprint(config, prompts: PromptSet) -> str:
    """Short identifier of a run configuration, used in the summary file."""
    payload = "|".join(
        [
            str(config.get("llm.provider")),
            str(config.get("llm.stage1_model")),
            str(config.get("llm.stage2_model")),
            str(config.get("llm.temperature")),
            prompts.fingerprint,
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
