# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Print default-configuration KPIs across the day. Used to calibrate network.yaml."""

from __future__ import annotations

import argparse
import time

from ranoversight.ransim import Network


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    t0 = time.perf_counter()
    net = Network(seed=args.seed)
    t1 = time.perf_counter()
    print(f"build {t1 - t0:.3f}s; users {net.users.n}; cells {len(net.layout.cell_ids)}")

    for h in (3, 10, 19, 21):
        t = time.perf_counter()
        k = net.kpis_at(h)
        dt = time.perf_counter() - t
        loads = [c.load for c in k.per_cell.values()]
        print(
            f"h{h:02d} cov {k.coverage_pct:5.1f}%  active {k.active_users:4d}  "
            f"mean {k.tput_mean_mbps:6.2f}  p5 {k.tput_p5_mbps:5.2f} Mbps  poor {k.poor_sinr_users:3d}  "
            f"load min/mean/max {min(loads):.2f}/{sum(loads) / len(loads):.2f}/{max(loads):.2f}  "
            f"conv {k.load_converged}  {dt * 1000:.0f} ms"
        )
        for zid, z in k.per_zone.items():
            print(f"     {zid} cov {z.coverage_pct:5.1f}%  active {z.active_users:3d}  "
                  f"mean {z.tput_mean_mbps:6.2f}  p5 {z.tput_p5_mbps:5.2f}")
    print("alarms at 19:00:", [(a.rule, a.subject, round(a.value, 2)) for a in net.alarms_at(19)])

    out = Network(seed=args.seed)
    out.set_site_down("S00")
    k = out.kpis_at(10)
    print(f"S00 down, h10: cov {k.coverage_pct:.1f}%  " +
          "  ".join(f"{z} {v.coverage_pct:.1f}%" for z, v in k.per_zone.items()))


if __name__ == "__main__":
    main()
