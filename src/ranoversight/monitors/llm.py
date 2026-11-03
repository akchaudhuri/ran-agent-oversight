# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""LLM monitors M1 to M4. A trusted, smaller model scores a recorded run.

Monitors run offline over saved run records, so every monitor sees exactly the
same runs and can be re-run cheaply. Model calls go through Inspect, so any
provider string works and the mockllm model can be used in tests.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

from inspect_ai.model import GenerateConfig, get_model

from ..transcript import RunRecord
from .m0_rules import MonitorScore
from .views import View, assert_clean, to_monitor_input

PROMPTS = Path(__file__).parent / "prompts"
TEMPLATE = (PROMPTS / "monitor.md").read_text()
CHECKLIST_FILE = PROMPTS / "m4_checklist.md"


@dataclass(frozen=True)
class LlmMonitor:
    monitor_id: str
    view: View
    use_checklist: bool = False


MONITORS = {
    "M1": LlmMonitor("M1", "actions"),
    "M2": LlmMonitor("M2", "actions_kpis"),
    "M3": LlmMonitor("M3", "full"),
    "M4": LlmMonitor("M4", "actions_kpis", use_checklist=True),
}


def checklist_text() -> str:
    raw = CHECKLIST_FILE.read_text()
    body = re.sub(r"<!--.*?-->", "", raw, flags=re.S).strip()
    if "CHECKLIST_NOT_FROZEN" in body:
        raise RuntimeError("M4 checklist is not frozen yet (monitors/prompts/m4_checklist.md).")
    return ("An experienced network operations engineer uses this checklist when reviewing changes. "
            "Apply it:\n" + body + "\n\n")


def build_prompt(rec: RunRecord, mon: LlmMonitor, upto_step: int | None = None) -> str:
    mi = to_monitor_input(rec, mon.view, upto_step)
    assert_clean(mi)
    return TEMPLATE.format(checklist=checklist_text() if mon.use_checklist else "", transcript=mi.text)


_SCORE = re.compile(r"<score>\s*(\d{1,3})\s*</score>", re.S)
_REASON = re.compile(r"<reason>(.*?)</reason>", re.S)


def parse(output: str) -> tuple[float | None, str]:
    m = _SCORE.search(output)
    reason = _REASON.search(output)
    score = float(min(100, int(m.group(1)))) if m else None
    return score, (reason.group(1).strip() if reason else output.strip()[:300])


async def score_one(rec: RunRecord, mon: LlmMonitor, model: str, sample: int,
                    upto_step: int | None = None, effort: str | None = "medium") -> MonitorScore:
    prompt = build_prompt(rec, mon, upto_step)
    cfg = GenerateConfig(effort=effort) if effort and not model.startswith("mockllm") else GenerateConfig()
    out = await get_model(model, config=cfg).generate(prompt)
    score, reason = parse(out.completion)
    usage = out.usage
    return MonitorScore(
        monitor=mon.monitor_id,
        score=-1.0 if score is None else score,      # -1 marks an unparseable answer (recorded as missing)
        reason=reason,
        tokens_in=int(getattr(usage, "input_tokens", 0) or 0),
        tokens_out=int(getattr(usage, "output_tokens", 0) or 0),
        sample=sample,
        upto_step=upto_step,
    )


async def score_runs(records: list[RunRecord], monitor_ids: list[str], model: str, samples: int = 3,
                     effort: str | None = "medium", concurrency: int = 8) -> list[tuple[str, MonitorScore]]:
    sem = asyncio.Semaphore(concurrency)

    async def job(rec: RunRecord, mid: str, k: int):
        async with sem:
            return rec.header["run_id"], await score_one(rec, MONITORS[mid], model, k, effort=effort)

    return await asyncio.gather(*[job(r, m, k) for r in records for m in monitor_ids for k in range(samples)])
