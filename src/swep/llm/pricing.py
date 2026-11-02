"""Token pricing and cost accounting (REQ-1.7).

Prices change over time, so they live in the YAML configuration rather than in
code.  Lookup tolerates dated model snapshots: ``gpt-4.1-2025-04-14`` is matched
by the ``gpt-4.1`` entry through the longest matching prefix.
"""

from typing import Dict, Mapping, Optional


class PriceTable:
    """USD price per 1M tokens, per model, with a configurable fallback."""

    def __init__(self, prices: Mapping[str, Mapping[str, float]], default: Optional[Mapping[str, float]] = None):
        self.prices = {str(k): dict(v) for k, v in (prices or {}).items()}
        self.default = dict(default or {"input": 0.0, "output": 0.0})

    @classmethod
    def from_config(cls, config) -> "PriceTable":
        return cls(
            prices=config.get("llm.budget.prices_per_1m_tokens", {}),
            default=config.get("llm.budget.default_price", None),
        )

    def _lookup(self, model: str) -> Dict[str, float]:
        model = str(model or "")
        if model in self.prices:
            return self.prices[model]
        candidates = [key for key in self.prices if model.startswith(key)]
        if candidates:
            return self.prices[max(candidates, key=len)]
        return self.default

    def cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Cost of one call in USD."""
        price = self._lookup(model)
        return (
            (prompt_tokens or 0) / 1_000_000.0 * float(price.get("input", 0.0))
            + (completion_tokens or 0) / 1_000_000.0 * float(price.get("output", 0.0))
        )
