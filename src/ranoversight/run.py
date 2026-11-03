# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Run episodes and export them to runs/*.jsonl.

Examples:
  python -m ranoversight.run --pilot                     # 3 honest + 3 attack, prints cost
  python -m ranoversight.run --mode honest               # all honest runs in config
  python -m ranoversight.run --mode attack --pairing outage:zone_degrade --attack-seeds 201 202
  python -m ranoversight.run --mode attack --policy scripted   # fallback attack policy, no API calls

Needs ANTHROPIC_API_KEY in the environment (or in a .env file in this folder,
which Inspect loads and git ignores) for --policy model.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from inspect_ai import eval as inspect_eval
from inspect_ai.model import GenerateConfig
from inspect_ai.tool import ToolCall

from control_arena import EvalMode
from control_arena.eval import ControlEvalConfig, get_control_task
from control_arena.policy import (
    attack_policy_builder,
    fixed_policy_builder,
    honest_policy_builder,
    untrusted_policy_builder,
)

from .cost import Ledger, SpendCapReached, load_run_config
from .setting import ATTACK_PROMPT_FILE, RanOversightSetting
from .tasks.scripted import SCRIPTED, SCRIPTED_ATTACKS
from .tasks.side import PAIRINGS
from .transcript import from_inspect_sample, write_run

PILOT_HONEST = [("outage", 101), ("stadium", 101), ("energy", 101)]
PILOT_ATTACK = [("outage", "zone_degrade", 201), ("stadium", "zone_degrade", 201), ("outage", "time_bomb", 201)]
# Rough per-run ceiling used only to stop before a batch would pass the cap.
EST_RUN_USD = 1.50


def _eval_config(cfg: dict, log_dir: str, policy: str) -> ControlEvalConfig:
    if policy == "scripted":
        return ControlEvalConfig(untrusted_model="mockllm/model", trusted_model="mockllm/model",
                                 max_steps=cfg["agent"]["max_steps"], log_dir=log_dir)
    return ControlEvalConfig(
        untrusted_model=cfg["models"]["agent"],
        trusted_model=cfg["models"]["monitor"],
        untrusted_config=GenerateConfig(effort=cfg["agent"]["effort"]),
        max_steps=cfg["agent"]["max_steps"],
        token_limit=cfg["agent"]["token_limit"],
        log_dir=log_dir,
        max_samples=4,
    )


def _model_policy():
    return untrusted_policy_builder(
        attack=attack_policy_builder(prompt_file=ATTACK_PROMPT_FILE),
        honest=honest_policy_builder(),
    )


def _scripted_policy(main_task: str, side_task: str | None):
    steps = SCRIPTED_ATTACKS[(main_task, side_task)] if side_task else SCRIPTED[main_task]["success"]
    calls = [ToolCall(id="s0", function="get_network_summary", arguments={})]
    fn = {"tilt": ("set_tilt", "degrees"), "power": ("set_power", "dbm"), "cio": ("set_cio", "db")}
    for i, (a, b, v) in enumerate(steps, start=1):
        if a == "@alarm":
            calls.append(ToolCall(id=f"s{i}", function="set_alarm_threshold",
                                  arguments={"name": b, "value": v, "reason": "reduce alarm noise during the work"}))
        else:
            name, arg = fn[b]
            calls.append(ToolCall(id=f"s{i}", function=name,
                                  arguments={"cell_id": a, arg: v, "reason": "optimisation step for the ticket"}))
    calls.append(ToolCall(id="end", function="submit_report",
                          arguments={"report": "Completed the ticket. Changes are listed in the change log."}))
    return fixed_policy_builder(tool_calls=calls)


def _export(logs, runs_dir: str, ledger: Ledger, policy: str, agent_model: str) -> list[dict]:
    rows = []
    for log in logs:
        if log.status != "success":
            print(f"  eval {log.eval.task} status {log.status}: {log.error}")
        for sample in log.samples or []:
            cost = ledger.add_inspect_usage(sample.model_usage)
            if sample.error is not None:
                msg = str(getattr(sample.error, "message", sample.error)).strip().splitlines()
                first = next((l for l in msg if "Error" in l or "error" in l), msg[0] if msg else "")
                print(f"  FAILED {sample.id}: {first[:300]}")
                rows.append({"run": None, "sample": str(sample.id), "error": first[:300],
                             "cost_usd": round(cost, 3)})
                continue
            rec = from_inspect_sample(sample, {"policy": policy, "agent_model": agent_model,
                                               "cost_usd": round(cost, 4)})
            path = write_run(rec, runs_dir)
            sc = rec.final["scores"]
            main = next((v for v in sc.values() if "main_task_success" in v), {})
            side = next((v for v in sc.values() if "side_task_success" in v), {})
            rows.append({"run": path.name, "sample": rec.header["sample_id"], "cost_usd": round(cost, 3),
                         "steps": len(rec.steps), "main": main.get("main_task_score"),
                         "side": side.get("side_task_success"), "report": rec.report[:80]})
    return rows


def run_batch(setting: RanOversightSetting, mode: EvalMode, policy, cfg: dict, args, ledger: Ledger,
              n_samples: int, label: str) -> list[dict]:
    ledger.check(n_samples * EST_RUN_USD if args.policy == "model" else 0.0)
    task = get_control_task(setting, policy, mode, eval_config=_eval_config(cfg, args.log_dir, args.policy),
                            task_name_prefix=label)
    t0 = time.time()
    logs = inspect_eval(task, log_dir=args.log_dir, display=args.display,
                        model=cfg["models"]["agent"] if args.policy == "model" else "mockllm/model")
    rows = _export(logs, args.runs_dir, ledger, args.policy,
                   cfg["models"]["agent"] if args.policy == "model" else "scripted")
    print(f"  {label}: {len(rows)} runs in {time.time() - t0:.0f}s, spent so far ${ledger.spent_usd:.2f}")
    for r in rows:
        print("   ", json.dumps(r))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=None)
    ap.add_argument("--pilot", action="store_true")
    ap.add_argument("--mode", choices=["honest", "attack", "both"], default="both")
    ap.add_argument("--policy", choices=["model", "scripted"], default="model")
    ap.add_argument("--main-tasks", nargs="*", default=None)
    ap.add_argument("--pairing", nargs="*", default=None, help="main:side, e.g. outage:zone_degrade")
    ap.add_argument("--honest-seeds", nargs="*", type=int, default=None)
    ap.add_argument("--attack-seeds", nargs="*", type=int, default=None)
    ap.add_argument("--named-zones", action="store_true", help="label ablation (D12)")
    ap.add_argument("--log-dir", default="logs")
    ap.add_argument("--runs-dir", default="runs")
    ap.add_argument("--display", default="rich")
    args = ap.parse_args()

    cfg = load_run_config(args.config)
    ledger = Ledger.from_config(cfg)
    rows: list[dict] = []
    try:
        if args.pilot:
            for main, seed in PILOT_HONEST:
                s = RanOversightSetting(main_tasks=[main], honest_seeds=[seed])
                batch = run_batch(s, EvalMode.HONEST, _model_policy(), cfg, args, ledger, 1, f"pilot_h_{main}")
                rows += batch
                if batch and all(r.get("error") for r in batch):
                    print("\nPilot STOPPED after the first failed run. Fix the error above and rerun.")
                    return
            for main, side, seed in PILOT_ATTACK:
                s = RanOversightSetting(main_tasks=[main], attack_pairings=[(main, side)], attack_seeds=[seed])
                rows += run_batch(s, EvalMode.ATTACK, _model_policy(), cfg, args, ledger, 1, f"pilot_a_{main}_{side}")
            n_full = 117   # PREREGISTRATION.md, section 3
            ok = [r for r in rows if not r.get("error")]
            failed = len(rows) - len(ok)
            if not ok:
                print(f"\nPilot FAILED: all {len(rows)} runs errored. No cost estimate. Fix the error above and rerun.")
                return
            per = ledger.spent_usd / len(ok)
            print(f"\nPilot: {len(ok)} runs completed, {failed} failed, ${ledger.spent_usd:.2f} "
                  f"(${per:.2f} per completed run). Full matrix of about {n_full} runs: ~${per * n_full:.0f}. "
                  f"Cap: ${ledger.cap_usd:.0f}.")
            if failed:
                print("WARNING: some runs failed; the estimate is based only on the completed ones.")
            return

        mains = args.main_tasks or ["outage", "stadium", "energy"]
        pairings = ([tuple(p.split(":")) for p in args.pairing] if args.pairing
                    else [p for p in PAIRINGS if p[0] in mains])
        honest_seeds = args.honest_seeds or cfg["seeds"]["honest"]
        attack_seeds = args.attack_seeds or cfg["seeds"]["attack"]

        if args.mode in ("honest", "both"):
            for main in mains:
                s = RanOversightSetting(main_tasks=[main], honest_seeds=honest_seeds, named_zones=args.named_zones)
                pol = _model_policy() if args.policy == "model" else _scripted_policy(main, None)
                rows += run_batch(s, EvalMode.HONEST, pol, cfg, args, ledger, len(honest_seeds), f"honest_{main}")
        if args.mode in ("attack", "both"):
            for main, side in pairings:
                s = RanOversightSetting(main_tasks=[main], attack_pairings=[(main, side)],
                                        attack_seeds=attack_seeds, named_zones=args.named_zones)
                pol = _model_policy() if args.policy == "model" else _scripted_policy(main, side)
                rows += run_batch(s, EvalMode.ATTACK, pol, cfg, args, ledger, len(attack_seeds),
                                  f"attack_{main}_{side}{'_named' if args.named_zones else ''}")
    except SpendCapReached as e:
        print(f"STOPPED: {e}")
    finally:
        failed = sum(1 for r in rows if r.get("error"))
        print(f"\nTotal: {len(rows) - failed} runs completed, {failed} failed, ${ledger.spent_usd:.2f} spent.")


if __name__ == "__main__":
    main()
