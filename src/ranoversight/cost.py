# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Token and spend accounting with a hard cap.

Prices come from config/default.yaml (USD per million tokens). Cache reads are
charged at 5% of the input price and cache writes at 125%, per the Claude
pricing page checked on 3 November 2026.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_RUN_CONFIG = Path(__file__).resolve().parents[2] / "config" / "default.yaml"


class SpendCapReached(RuntimeError):
    pass


def load_run_config(path: str | Path | None = None) -> dict[str, Any]:
    return yaml.safe_load(Path(path or DEFAULT_RUN_CONFIG).read_text())


def _norm(model: str) -> str:
    return model if "/" in model else f"anthropic/{model}"


@dataclass
class Ledger:
    prices: dict[str, tuple[float, float]]
    cap_usd: float
    spent_usd: float = 0.0
    by_model: dict[str, float] = field(default_factory=dict)

    @classmethod
    def from_config(cls, cfg: dict[str, Any]) -> "Ledger":
        prices = {_norm(k): (float(v[0]), float(v[1])) for k, v in cfg["spend"]["prices"].items()}
        return cls(prices=prices, cap_usd=float(cfg["spend"]["hard_cap_usd"]))

    def cost(self, model: str, inp: int, out: int, cache_read: int = 0, cache_write: int = 0) -> float:
        m = _norm(model)
        if m.startswith("mockllm"):
            return 0.0
        if m not in self.prices:
            raise KeyError(f"no price for {m}; add it to config/default.yaml")
        pin, pout = self.prices[m]
        return (inp * pin + out * pout + cache_read * pin * 0.05 + cache_write * pin * 1.25) / 1e6

    def add(self, model: str, inp: int, out: int, cache_read: int = 0, cache_write: int = 0) -> float:
        c = self.cost(model, inp, out, cache_read, cache_write)
        self.spent_usd += c
        self.by_model[_norm(model)] = self.by_model.get(_norm(model), 0.0) + c
        return c

    def add_inspect_usage(self, model_usage: dict[str, Any]) -> float:
        total = 0.0
        for model, u in (model_usage or {}).items():
            total += self.add(model, int(u.input_tokens or 0), int(u.output_tokens or 0),
                              int(getattr(u, "input_tokens_cache_read", 0) or 0),
                              int(getattr(u, "input_tokens_cache_write", 0) or 0))
        return total

    def check(self, next_estimate_usd: float = 0.0) -> None:
        """Raise before work whose estimated cost would take spend past the cap."""
        if self.spent_usd + next_estimate_usd > self.cap_usd:
            raise SpendCapReached(
                f"spent ${self.spent_usd:.2f}; next batch ~${next_estimate_usd:.2f} would pass the "
                f"${self.cap_usd:.0f} cap")
