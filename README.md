# ran-agent-oversight

Can a monitor tell a harmful network change from a normal optimisation step?

This repository is building an AI control evaluation in which a Claude agent operates a simulated mobile radio network, sometimes with a hidden harmful goal, and monitors try to catch it. Work in progress; results will be published here by 20 November 2026. The design is in [ARCHITECTURE.md](ARCHITECTURE.md).

## Status

| Part | State |
|---|---|
| Network simulator (`ransim`) | Built, 45 tests passing |
| Agent tools, tasks, ControlArena setting | Next |
| Side tasks and monitors | Planned |
| Full run and analysis | Planned |

## The simulator

A deliberately small, deterministic model: 19 sites at 750 m spacing with 3 sectors each, of which the central 7 sites (21 cells) can be changed. Standard macro path loss, a 3GPP-style sector antenna, log-normal shadowing, building entry loss, and load-coupled interference solved by fixed-point iteration. 1,000 static users in four zones with hourly traffic profiles. Every change is logged and reversible, and the same seed with the same actions gives identical results.

It is not a system-level simulator. There is no fading, mobility, scheduler or uplink, and throughput is a Shannon-bound share. The aim is that changes to tilt, power and handover offsets have the qualitative effects an RF engineer expects, which the sanity plots in `results/sanity/` check.

## Run it

```
pip install -e ".[dev]"
pytest
python scripts/sanity_plots.py --out results/sanity
```

## Independence

No code, data, methods or customer information from Advaya Networks are used. The simulator is built only from public models and parameters, and nothing here touches real network equipment or interfaces.

## Licence

Apache-2.0. Copyright 2026 Aditya Chaudhuri.
