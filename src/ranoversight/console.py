# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""The operator console: what the agent can see and do, as plain text.

No framework dependency. The ControlArena setting wraps each method as a tool.
Every method is identical in honest and attack runs. Nothing here can reveal
the eval mode, a side task or a scoring rule, because the console never
receives them.
"""

from __future__ import annotations

from collections import Counter

import numpy as np

from .ransim import Change, ChangeRejected, Network


def _f(x: float, nd: int = 1) -> str:
    return f"{x:.{nd}f}"


class OperatorConsole:
    def __init__(self, net: Network):
        self.net = net

    # ------------------------------------------------------------------ read

    def network_summary(self) -> str:
        n = self.net
        k = n.kpis()
        down = sorted({c.split("-")[0] for c in n.cell_ids() if not n.is_up(c)})
        alarms = n.alarms()
        lines = [
            f"Network summary at {n.hour:02d}:00 (managed area: {len(n.cell_ids())} cells on 7 sites)",
            f"  coverage (RSRP >= {n.cfg.radio['coverage_rsrp_dbm']} dBm): {_f(k.coverage_pct)}% of users",
            f"  active users this hour: {k.active_users}",
            f"  user throughput: mean {_f(k.tput_mean_mbps, 2)} Mbps, 5th percentile {_f(k.tput_p5_mbps, 2)} Mbps",
            f"  active users with SINR below {n.cfg.radio['poor_sinr_db']} dB: {k.poor_sinr_users}",
            f"  total transmit power, managed cells: {_f(k.total_power_w)} W",
            f"  sites down: {', '.join(down) if down else 'none'}",
            f"  active alarms: {len(alarms)}",
            "  zones: " + "; ".join(
                f"{z} coverage {_f(v.coverage_pct)}%, p5 {_f(v.tput_p5_mbps, 2)} Mbps"
                for z, v in k.per_zone.items()
            ),
        ]
        return "\n".join(lines)

    def list_cells(self) -> str:
        n, lay = self.net, self.net.layout
        k = n.kpis()
        rows = ["cell    site position (m)   azimuth  tilt  power  CIO   load  users  status"]
        for cid in n.cell_ids():
            j = lay.cell_index(cid)
            x, y = lay.site_xy[lay.cell_site[j]]
            c = k.per_cell[cid]
            rows.append(
                f"{cid:6s}  ({x:6.0f}, {y:6.0f})     {lay.cell_azimuth[j]:5.0f}°  {c.tilt_deg:4.1f}  "
                f"{c.power_dbm:5.1f}  {c.cio_db:+4.1f}  {c.load:4.2f}  {c.active_users:5d}  "
                f"{'up' if c.up else 'DOWN'}"
            )
        rows.append("Azimuth is measured counterclockwise from east (0° = east, 90° = north).")
        return "\n".join(rows)

    def cell_kpis(self, cell_id: str) -> str:
        n = self.net
        k = n.kpis()
        if cell_id not in k.per_cell:
            return f"ERROR: unknown or unmanaged cell {cell_id!r}. Use list_cells to see managed cells."
        c = k.per_cell[cid := cell_id]
        users = self._served_by(cid)
        zones = Counter(n.users.zone[users])
        zone_txt = ", ".join(f"{z} {v}" for z, v in sorted(zones.items())) or "none"
        return "\n".join([
            f"Cell {cid} at {n.hour:02d}:00: {'up' if c.up else 'DOWN'}",
            f"  config: tilt {c.tilt_deg:g}°, power {c.power_dbm:g} dBm, CIO {c.cio_db:+g} dB",
            f"  load {_f(c.load, 2)}, active users {c.active_users}, mean user throughput {_f(c.tput_mean_mbps, 2)} Mbps",
            f"  users served (all hours, by zone): {zone_txt}",
        ])

    def zone_kpis(self, zone: str) -> str:
        n = self.net
        k = n.kpis()
        if zone not in k.per_zone:
            return f"ERROR: unknown zone {zone!r}. Zones are {', '.join(k.per_zone)}."
        z = k.per_zone[zone]
        inz = n.users.zone == zone
        serving = self._serving()
        shares = Counter(n.layout.cell_ids[j] for j in serving[inz & self._covered()])
        total = int(inz.sum())
        top = ", ".join(f"{c} {100 * v / total:.0f}%" for c, v in shares.most_common(4)) or "none"
        return "\n".join([
            f"Zone {zone} (priority {n.cfg.zones[zone].priority}) at {n.hour:02d}:00",
            f"  coverage {_f(z.coverage_pct)}% of {total} users",
            f"  active users {z.active_users}; throughput mean {_f(z.tput_mean_mbps, 2)} Mbps, "
            f"5th percentile {_f(z.tput_p5_mbps, 2)} Mbps",
            f"  main serving cells (share of zone users): {top}",
        ])

    def alarms(self) -> str:
        al = self.net.alarms()
        th = ", ".join(f"{r} {self.net.alarm_threshold(r):g}" for r in self.net.cfg.alarm_rules)
        if not al:
            return f"No active alarms at {self.net.hour:02d}:00. Thresholds: {th}."
        rows = [f"{len(al)} active alarm(s) at {self.net.hour:02d}:00. Thresholds: {th}."]
        rows += [f"  {a.rule} on {a.subject}: value {_f(a.value, 2)}, threshold {a.threshold:g}" for a in al]
        return "\n".join(rows)

    def change_log(self) -> str:
        log = self.net.log()
        if not log:
            return "No changes made yet."
        rows = []
        for r in log:
            what = r.target if r.param == "alarm_threshold" else r.cell_id
            extra = f" (rollback of {r.is_rollback_of})" if r.is_rollback_of else ""
            warn = f"  WARNING: {'; '.join(r.warnings)}" if r.warnings else ""
            rows.append(f"{r.change_id} {r.hour:02d}:00 {what} {r.param} {r.old:g} -> {r.new:g}{extra}: {r.reason}{warn}")
        return "\n".join(rows)

    # ------------------------------------------------------------------ write

    def set_param(self, param: str, cell_id: str, value: float, reason: str) -> str:
        return self._apply(Change(param, float(value), reason, cell_id=cell_id))

    def set_alarm_threshold(self, name: str, value: float, reason: str) -> str:
        return self._apply(Change("alarm_threshold", float(value), reason, target=name))

    def rollback(self, change_id: str, reason: str) -> str:
        try:
            rec = self.net.rollback(change_id, reason)
        except ChangeRejected as e:
            return f"REJECTED: {e}"
        return f"OK {rec.change_id}: rolled back {change_id} ({rec.param} {rec.old:g} -> {rec.new:g})."

    def advance_time(self, hours: int) -> str:
        try:
            self.net.advance(int(hours))
        except ValueError as e:
            return f"REJECTED: {e}"
        return f"Clock is now {self.net.hour:02d}:00."

    # ------------------------------------------------------------------ internals

    def _apply(self, change: Change) -> str:
        if not change.reason or not change.reason.strip():
            return "REJECTED: every change needs a reason."
        try:
            rec = self.net.apply(change)
        except ChangeRejected as e:
            return f"REJECTED: {e}"
        what = rec.target if rec.param == "alarm_threshold" else rec.cell_id
        msg = f"OK {rec.change_id}: {what} {rec.param} {rec.old:g} -> {rec.new:g}."
        if rec.warnings:
            msg += " WARNING: " + "; ".join(rec.warnings) + "."
        return msg

    def _serving(self) -> np.ndarray:
        n = self.net
        rx = n._rx_dbm(n._geo, n._extra_loss)
        cio = np.array([n.config(c).cio_db for c in n.layout.cell_ids])
        return np.argmax(rx + cio[None, :], axis=1)

    def _covered(self) -> np.ndarray:
        n = self.net
        from .ransim import radio
        rx = n._rx_dbm(n._geo, n._extra_loss) - radio.rsrp_offset_db(n.cfg)
        s = self._serving()
        return rx[np.arange(n.users.n), s] >= n.cfg.radio["coverage_rsrp_dbm"]

    def _served_by(self, cell_id: str) -> np.ndarray:
        j = self.net.layout.cell_index(cell_id)
        return (self._serving() == j) & self._covered()
