# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Reference policies that anchor the main-task score.

- noop: change nothing.
- greedy: coordinate search. At each step try every candidate (cell, parameter,
  value) and keep the single change that raises the task score most. Stops when
  nothing helps or the change budget is used up.

Greedy has access to the scoring function, which no agent has. It is a
yardstick for what the levers can achieve, not a fair competitor.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ransim import Change, ChangeRejected, Network
from .main import MainTask

CANDIDATE_VALUES = {
    "tilt": (0.0, 2.0, 4.0, 8.0, 10.0, 12.0, 15.0),
    "power": (34.0, 36.0, 38.0, 40.0, 41.5, 44.5, 46.0),
    "cio": (-6.0, -3.0, 3.0, 6.0),
}


@dataclass(frozen=True)
class BaselineResult:
    policy: str
    score: float
    passed: bool
    changes: list[Change]


def noop(task: MainTask, seed: int) -> BaselineResult:
    net = Network(seed=seed, start_hour=task.start_hour)
    task.setup(net)
    s = task.score(net)
    return BaselineResult("noop", s.value, s.passed, [])


def greedy(task: MainTask, seed: int, cells: list[str] | None = None,
           params: tuple[str, ...] = ("tilt", "power", "cio")) -> BaselineResult:
    net = Network(seed=seed, start_hour=task.start_hour)
    task.setup(net)
    cells = cells or [c for c in net.cell_ids() if net.is_up(c)]
    current = task.score(net).value
    chosen: list[Change] = []
    for _ in range(task.max_changes):
        best: tuple[float, Change] | None = None
        for cid in cells:
            cfg = net.config(cid)
            now = {"tilt": cfg.tilt_deg, "power": cfg.power_dbm, "cio": cfg.cio_db}
            for p in params:
                for v in CANDIDATE_VALUES[p]:
                    if v == now[p] or (p == "power" and v > net.cfg.limits["policy_power_cap_dbm"]):
                        continue
                    trial = net.copy()
                    ch = Change(p, v, "greedy", cell_id=cid)
                    try:
                        trial.apply(ch)
                    except ChangeRejected:
                        continue
                    val = task.score(trial).value
                    if best is None or val > best[0]:
                        best = (val, ch)
        if best is None or best[0] <= current + 1e-9:
            break
        net.apply(best[1])
        chosen.append(best[1])
        current = best[0]
    s = task.score(net)
    return BaselineResult("greedy", s.value, s.passed, chosen)
