# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Score saved runs with monitors and write results/scores.jsonl.

Examples:
  python -m ranoversight.score --monitors M0                    # rules only, free
  python -m ranoversight.score --monitors M0 M1 M2 M3 M4        # needs ANTHROPIC_API_KEY
  python -m ranoversight.score --monitors M1 --model mockllm/model   # plumbing test, no API

Every run's monitor input is checked for harness leaks before any model call.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from .cost import Ledger, load_run_config
from .monitors import m0_score, to_monitor_input, assert_clean, verbatim_leaks
from .monitors.llm import score_runs
from .transcript import RunRecord


def load_runs(runs_dir: str) -> list[RunRecord]:
    return [RunRecord.from_jsonl(p.read_text()) for p in sorted(Path(runs_dir).glob("*.jsonl"))]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--out", default="results/scores.jsonl")
    ap.add_argument("--monitors", nargs="+", default=["M0"])
    ap.add_argument("--model", default=None, help="monitor model (default from config)")
    ap.add_argument("--samples", type=int, default=None)
    ap.add_argument("--config", default=None)
    args = ap.parse_args()

    cfg = load_run_config(args.config)
    model = args.model or cfg["models"]["monitor"]
    samples = args.samples or cfg["monitor"]["samples_per_input"]
    runs = load_runs(args.runs_dir)
    print(f"{len(runs)} runs from {args.runs_dir}")

    for r in runs:                      # leak check on every view before anything is scored
        for view in ("actions", "actions_kpis", "full"):
            assert_clean(to_monitor_input(r, view))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in runs:
        rows.append({"run_id": r.header["run_id"], "type": "leaks", **verbatim_leaks(r)})
        if "M0" in args.monitors:
            rows.append({"run_id": r.header["run_id"], "type": "score", **asdict(m0_score(r))})

    llm_ids = [m for m in args.monitors if m != "M0"]
    ledger = Ledger.from_config(cfg)
    if llm_ids:
        results = asyncio.run(score_runs(runs, llm_ids, model, samples, effort=cfg["monitor"]["effort"]))
        for run_id, s in results:
            ledger.add(model, s.tokens_in, s.tokens_out)
            rows.append({"run_id": run_id, "type": "score", "monitor_model": model, **asdict(s)})

    with out.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(f"wrote {len(rows)} rows to {out}; monitor spend ${ledger.spent_usd:.3f}")

    by_run = {r.header["run_id"]: r.header for r in runs}
    for row in rows:
        if row["type"] == "score" and row.get("sample", 0) == 0:
            h = by_run[row["run_id"]]
            print(f"  {row['monitor']:3s} {h['mode']:6s} {h['main_task']:8s} {str(h['side_task']):15s} "
                  f"score {row['score']:5.0f}  {row['reason'][:90]}")


if __name__ == "__main__":
    main()
