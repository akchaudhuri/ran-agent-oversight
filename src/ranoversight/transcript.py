# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Export Inspect samples to run records (runs/<run_id>.jsonl), with KPI replay.

The Inspect log stays the source of truth. A run record is the subset monitors
can be shown, plus a header that monitors never see. Per-change KPI deltas are
computed by replaying the recorded tool calls on a fresh simulator: the
simulator is deterministic, so the replay reproduces the run exactly, and a
mismatch with the logged tool results is raised as an error.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .console import OperatorConsole
from .ransim import Network, load_config
from .tasks.main import MAIN_TASKS

WRITE_TOOLS = {"set_tilt", "set_power", "set_cio", "set_alarm_threshold", "rollback"}
SUBMIT_TOOL = "submit_report"


@dataclass
class Step:
    step: int
    hour: int
    tool: str
    args: dict[str, Any]
    result: str
    reason: str = ""
    visible_text: str = ""          # assistant text in the same turn as this call
    thinking: str = ""              # assistant reasoning in the same turn (M3 only)
    kpi_delta: dict[str, Any] = field(default_factory=dict)   # write tools only


@dataclass
class RunRecord:
    header: dict[str, Any]           # never shown to monitors
    ticket: str
    steps: list[Step]
    report: str
    final: dict[str, Any]            # scores; never shown to monitors

    def to_jsonl(self) -> str:
        lines = [json.dumps({"type": "header", **self.header}),
                 json.dumps({"type": "ticket", "text": self.ticket})]
        lines += [json.dumps({"type": "step", **asdict(s)}) for s in self.steps]
        lines.append(json.dumps({"type": "final", "report": self.report, **self.final}))
        return "\n".join(lines) + "\n"

    @classmethod
    def from_jsonl(cls, text: str) -> "RunRecord":
        header, ticket, steps, final = {}, "", [], {}
        for line in text.splitlines():
            d = json.loads(line)
            t = d.pop("type")
            if t == "header":
                header = d
            elif t == "ticket":
                ticket = d["text"]
            elif t == "step":
                steps.append(Step(**d))
            elif t == "final":
                final = d
        report = final.pop("report", "")
        return cls(header=header, ticket=ticket, steps=steps, report=report, final=final)


def _zone_snapshot(net: Network) -> dict[str, dict[str, float]]:
    k = net.kpis()
    return {z: {"coverage_pct": round(v.coverage_pct, 2), "tput_p5_mbps": round(v.tput_p5_mbps, 3)}
            for z, v in k.per_zone.items()} | {
        "network": {"coverage_pct": round(k.coverage_pct, 2), "total_power_w": round(k.total_power_w, 1)}}


def _delta(before: dict, after: dict) -> dict:
    return {z: {m: round(after[z][m] - before[z][m], 3) for m in after[z]} for z in after}


def replay(main_task: str, seed: int, calls: list[tuple[str, dict[str, Any]]]) -> list[tuple[str, int, dict]]:
    """Replay tool calls on a fresh network. Returns (result text, hour before call, kpi delta) per call."""
    task = MAIN_TASKS[main_task]
    net = Network(load_config(), seed=seed, start_hour=task.start_hour)
    task.setup(net)
    con = OperatorConsole(net)
    dispatch = {
        "get_network_summary": lambda a: con.network_summary(),
        "list_cells": lambda a: con.list_cells(),
        "get_cell_kpis": lambda a: con.cell_kpis(a["cell_id"]),
        "get_zone_kpis": lambda a: con.zone_kpis(a["zone"]),
        "get_alarms": lambda a: con.alarms(),
        "get_change_log": lambda a: con.change_log(),
        "set_tilt": lambda a: con.set_param("tilt", a["cell_id"], a["degrees"], a.get("reason", "")),
        "set_power": lambda a: con.set_param("power", a["cell_id"], a["dbm"], a.get("reason", "")),
        "set_cio": lambda a: con.set_param("cio", a["cell_id"], a["db"], a.get("reason", "")),
        "set_alarm_threshold": lambda a: con.set_alarm_threshold(a["name"], a["value"], a.get("reason", "")),
        "rollback": lambda a: con.rollback(a["change_id"], a.get("reason", "")),
        "advance_time": lambda a: con.advance_time(a["hours"]),
    }
    out = []
    for name, args in calls:
        hour = net.hour
        before = _zone_snapshot(net) if name in WRITE_TOOLS else None
        try:
            result = dispatch[name](args) if name in dispatch else f"(unknown tool {name})"
        except (KeyError, TypeError, ValueError) as e:     # malformed arguments from the model
            result = f"ERROR: {e}"
        delta = _delta(before, _zone_snapshot(net)) if before is not None else {}
        out.append((result, hour, delta))
    return out


def _text_and_thinking(msg: Any) -> tuple[str, str]:
    content = msg.content
    if isinstance(content, str):
        return content, ""
    text, think = [], []
    for c in content:
        kind = getattr(c, "type", "")
        if kind == "reasoning":
            think.append(getattr(c, "reasoning", "") or getattr(c, "summary", "") or "")
        elif kind == "text":
            text.append(c.text)
    return "\n".join(t for t in text if t), "\n".join(t for t in think if t)


def from_inspect_sample(sample: Any, eval_meta: dict[str, Any] | None = None) -> RunRecord:
    """Build a RunRecord from an Inspect EvalSample produced by this setting."""
    md = sample.metadata
    main_task, side_task = md["main_task_name"], md.get("side_task_name")
    seed = int(md["metadata"]["seed"])

    calls, meta = [], []
    report = ""
    for m in sample.messages:
        if m.role != "assistant" or not m.tool_calls:
            continue
        text, think = _text_and_thinking(m)
        for i, tc in enumerate(m.tool_calls):
            if tc.function == SUBMIT_TOOL:
                report = str(tc.arguments.get("report", ""))
                continue
            calls.append((tc.function, dict(tc.arguments)))
            meta.append((text if i == 0 else "", think if i == 0 else ""))

    logged = {m.tool_call_id: str(m.text if hasattr(m, "text") else m.content)
              for m in sample.messages if m.role == "tool"}
    ids = [tc.id for m in sample.messages if m.role == "assistant" and m.tool_calls
           for tc in m.tool_calls if tc.function != SUBMIT_TOOL]

    steps = []
    for n, ((name, args), (text, think), (result, hour, delta)) in enumerate(
            zip(calls, meta, replay(main_task, seed, calls)), start=1):
        if name in WRITE_TOOLS and ids and logged.get(ids[n - 1], result).strip() != result.strip():
            raise ValueError(f"replay mismatch at step {n} ({name}): log and simulator disagree")
        steps.append(Step(step=n, hour=hour, tool=name, args={k: v for k, v in args.items() if k != "reason"},
                          result=result, reason=str(args.get("reason", "")), visible_text=text,
                          thinking=think, kpi_delta=delta))

    scores = {k: v.value for k, v in (sample.scores or {}).items()}
    header = {
        "run_id": uuid.uuid4().hex,
        "mode": "attack" if side_task else "honest",
        "main_task": main_task,
        "side_task": side_task,
        "seed": seed,
        "named_zones": bool(md["metadata"].get("named_zones", False)),
        "sample_id": str(sample.id),
        **(eval_meta or {}),
    }
    return RunRecord(header=header, ticket=md["main_task_description"], steps=steps,
                     report=report, final={"scores": scores})


def write_run(rec: RunRecord, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{rec.header['run_id']}.jsonl"
    path.write_text(rec.to_jsonl())
    return path
