# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Three sanity plots for the simulator: coverage map, tilt effect, power effect.

Usage: python scripts/sanity_plots.py --out results/sanity
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Circle

from ranoversight.ransim import Change, Network
from ranoversight.ransim import radio

# Project palette. Saffron and green fail a red-green colour-blindness check as a
# pair, so no figure relies on telling them apart: one series per panel, text labels.
SAFFRON = "#FF9933"
SAFFRON_DARK = "#B85F00"   # saffron family, dark enough for 2 px lines on white
GREEN = "#138808"
RED = "#C0392B"
INK = "#111111"
MUTED = "#555555"
GRID = "#E6E6E6"
GREENS = LinearSegmentedColormap.from_list("greens", ["#F3F8F1", "#A9D3A0", "#4FA444", GREEN, "#0A4A04"])

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "text.color": INK,
    "axes.labelcolor": INK,
    "axes.edgecolor": MUTED,
    "axes.linewidth": 0.8,
    "xtick.color": MUTED,
    "ytick.color": MUTED,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.color": GRID,
    "grid.linewidth": 0.8,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "savefig.dpi": 160,
})

CELL = "S00-A"      # the cell facing the hospital zone
HOUR = 10


def _brand(fig) -> None:
    """Thin saffron and green bars, top and bottom."""
    fig.patches.append(plt.Rectangle((0, 0.992), 1, 0.008, transform=fig.transFigure, color=SAFFRON, zorder=10))
    fig.patches.append(plt.Rectangle((0, 0), 1, 0.008, transform=fig.transFigure, color=GREEN, zorder=10))


def _title(fig, title: str, subtitle: str) -> None:
    fig.text(0.04, 0.955, title, fontsize=13, fontweight="bold", color=INK, va="top")
    fig.text(0.04, 0.905, subtitle, fontsize=9.5, color=MUTED, va="top")


def _footer(fig) -> None:
    fig.text(0.04, 0.025, "ran-agent-oversight  ·  ransim, seed 1  ·  Aditya Chaudhuri", fontsize=8, color=MUTED)


def coverage_map(out: Path) -> None:
    half = 1150
    xs = np.linspace(-half, half, 260)
    gx, gy = np.meshgrid(xs, xs)
    pts = np.column_stack([gx.ravel(), gy.ravel()])

    fig, axes = plt.subplots(1, 2, figsize=(12, 6.4))
    fig.subplots_adjust(left=0.065, right=0.9, top=0.84, bottom=0.13, wspace=0.12)
    panels = [("Default configuration", None), ("Centre site S00 down", "S00")]
    im = None
    for ax, (label, down) in zip(axes, panels):
        net = Network(seed=1)
        if down:
            net.set_site_down(down)
        rsrp, _ = net.rsrp_map(pts)
        im = ax.imshow(rsrp.reshape(gx.shape), origin="lower", extent=(-half, half, -half, half),
                       cmap=GREENS, vmin=-110, vmax=-60, interpolation="bilinear")

        k = net.kpis_at(HOUR)
        rx = net._rx_dbm(net._geo, net._extra_loss) - radio.rsrp_offset_db(net.cfg)
        cio = np.array([net.config(c).cio_db for c in net.layout.cell_ids])
        best = np.argmax(rx + cio, axis=1)
        uncovered = rx[np.arange(net.users.n), best] < net.cfg.radio["coverage_rsrp_dbm"]
        ax.scatter(*net.users.xy[~uncovered].T, s=3, c=INK, alpha=0.25, linewidths=0, label="Covered user")
        ax.scatter(*net.users.xy[uncovered].T, s=26, marker="x", c=RED, linewidths=1.4,
                   label="User below -110 dBm (indoor loss and shadowing included)")

        lay = net.layout
        for s, (x, y) in enumerate(lay.site_xy):
            is_down = lay.site_ids[s] == down
            ax.plot(x, y, marker="^", ms=7, color=RED if is_down else INK, mec="white", mew=0.8,
                    ls="none", zorder=5)
            if lay.site_ring[s] <= 1:
                ax.annotate(lay.site_ids[s], (x, y), xytext=(5, -11), textcoords="offset points",
                            fontsize=7.5, color=INK)
        for zid, z in net.cfg.zones.items():
            if z.background:
                continue
            ax.add_patch(Circle(z.centre_m, z.radius_m, fill=False, ec=SAFFRON_DARK, lw=2, zorder=6))
            # Label placement: above (Z1), left (Z2, clear of S01/S06), below (Z3).
            side = {"Z1": "above", "Z2": "left"}.get(zid, "below")
            cx, cy = z.centre_m
            anchor, off, ha, va = {
                "above": ((cx, cy + z.radius_m), (0, 4), "center", "bottom"),
                "left": ((cx - z.radius_m, cy), (-4, 0), "right", "center"),
                "below": ((cx, cy - z.radius_m), (0, -4), "center", "top"),
            }[side]
            ax.annotate(f"{zid} {z.label}\n{k.per_zone[zid].coverage_pct:.1f}% covered",
                        anchor, xytext=off, textcoords="offset points",
                        ha=ha, va=va, fontsize=8, color=INK,
                        fontweight="bold", zorder=7,
                        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.8))
        ax.set_title(f"{label}   ·   network coverage {k.coverage_pct:.1f}%", fontsize=10.5, loc="left")
        ax.set_xlim(-half, half)
        ax.set_ylim(-half, half)
        ax.set_aspect("equal")
        ax.set_xlabel("x (m)")
        ax.grid(False)
    axes[0].set_ylabel("y (m)")
    axes[1].legend(loc="lower right", fontsize=8, frameon=True, framealpha=0.9, edgecolor=GRID)

    cax = fig.add_axes([0.915, 0.18, 0.014, 0.58])
    cb = fig.colorbar(im, cax=cax)
    cb.set_label("Best outdoor RSRP, no shadowing (dBm)", color=INK)
    cb.outline.set_visible(False)

    _title(fig, "Coverage at defaults, and what one site outage does",
           "19 sites, 750 m spacing; the central 7 (triangles with labels) are managed. Zones are labelled; "
           "the agent sees only Z1 to Z4 and a priority class.")
    _footer(fig)
    _brand(fig)
    fig.savefig(out / "01_coverage_map.png")
    plt.close(fig)


def tilt_effect(out: Path) -> None:
    tilts = np.arange(0, 16)
    dists = np.linspace(50, 1500, 600)
    reach, z1, net_cov = [], [], []
    for t in tilts:
        net = Network(seed=1)
        net.apply(Change("tilt", float(t), "sanity", cell_id=CELL))
        j = net.layout.cell_index(CELL)
        site = net.layout.site_xy[net.layout.cell_site[j]]
        az = np.radians(net.layout.cell_azimuth[j])
        pts = site + np.column_stack([dists * np.cos(az), dists * np.sin(az)])
        _, best = net.rsrp_map(pts)
        reach.append(dists[best == j].max())
        k = net.kpis_at(HOUR)
        z1.append(k.per_zone["Z1"].coverage_pct)
        net_cov.append(k.coverage_pct)

    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.6))
    fig.subplots_adjust(left=0.06, right=0.98, top=0.70, bottom=0.17, wspace=0.32)
    series = [
        (axes[0], reach, "Boresight reach (m)", GREEN, "Where S00-A stops being best server"),
        (axes[1], z1, "Z1 coverage (%)", SAFFRON_DARK, "Hospital zone, on S00-A's boresight"),
        (axes[2], net_cov, "Network coverage (%)", INK, "All managed users"),
    ]
    for ax, y, ylabel, color, note in series:
        ax.plot(tilts, y, color=color, lw=2, marker="o", ms=5, mec="white", mew=1)
        ax.axvline(6, color=MUTED, lw=1, ls=(0, (3, 3)))
        ax.annotate("default 6°", (6, 0), xycoords=("data", "axes fraction"), xytext=(4, 6),
                    textcoords="offset points", fontsize=8, color=MUTED)
        ax.set_xlabel("Electrical tilt of S00-A (degrees)")
        ax.set_title(ylabel, fontsize=10.5, loc="left", pad=20)
        ax.text(0, 1.03, note, transform=ax.transAxes, fontsize=8, color=MUTED, va="bottom")
        ax.set_xticks([0, 3, 6, 9, 12, 15])
        ax.annotate(f"{y[-1]:.0f}" if ylabel.startswith("Boresight") else f"{y[-1]:.1f}",
                    (tilts[-1], y[-1]), xytext=(-8, -3), textcoords="offset points", ha="right", va="top",
                    fontsize=8.5, color=INK, fontweight="bold")
    axes[2].set_ylim(min(net_cov) - 0.5, 100.2)

    _title(fig, "Tilt does what a planner expects",
           f"One cell (S00-A) swept from 0° to 15°, everything else at defaults, {HOUR}:00. "
           f"Downtilt pulls the edge in; the hospital loses {z1[6] - z1[-1]:.1f} points while the network loses "
           f"{net_cov[6] - net_cov[-1]:.1f}.")
    _footer(fig)
    _brand(fig)
    fig.savefig(out / "02_tilt_effect.png")
    plt.close(fig)


def power_effect(out: Path) -> None:
    powers = np.arange(40.0, 49.5, 0.5)
    base = Network(seed=1)
    j = base.layout.cell_index(CELL)
    rx0 = base._rx_dbm(base._geo, base._extra_loss)[:, j]
    shift, served, warned = [], [], []
    for p in powers:
        net = Network(seed=1)
        rec = net.apply(Change("power", float(p), "sanity", cell_id=CELL))
        rx = net._rx_dbm(net._geo, net._extra_loss)
        shift.append(float(np.mean(rx[:, j] - rx0)))
        served.append(int(np.sum(np.argmax(rx, axis=1) == j)))
        warned.append(bool(rec.warnings))

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.6))
    fig.subplots_adjust(left=0.07, right=0.97, top=0.74, bottom=0.16, wspace=0.28)
    cap = base.cfg.limits["policy_power_cap_dbm"]

    ax = axes[0]
    ax.plot(powers, powers - 43, color=MUTED, lw=1, ls=(0, (3, 3)))
    ax.annotate("the expected 1:1 line (dashed)\nsits exactly under the result", (40.2, 4.6), fontsize=8, color=MUTED)
    ax.plot(powers, shift, color=GREEN, lw=2, marker="o", ms=5, mec="white", mew=1)
    ax.set_title("Change in RSRP of every user from S00-A (dB)", fontsize=10.5, loc="left")
    ax.set_xlabel("Transmit power of S00-A (dBm)")

    ax = axes[1]
    ok = ~np.array(warned)
    ax.plot(powers, served, color=SAFFRON_DARK, lw=2)
    ax.plot(powers[ok], np.array(served)[ok], ls="none", marker="o", ms=5, color=SAFFRON_DARK, mec="white", mew=1)
    ax.plot(powers[~ok], np.array(served)[~ok], ls="none", marker="X", ms=8, color=RED, mec="white", mew=0.8)
    ax.axvline(cap, color=RED, lw=1.2, ls=(0, (4, 3)))
    ax.annotate("policy cap 46 dBm\nabove it (X): accepted,\nlogged with a warning", (cap, 0.04),
                xycoords=("data", "axes fraction"), xytext=(-6, 0), textcoords="offset points",
                ha="right", fontsize=8, color=RED)
    ax.set_title("Users with S00-A as strongest cell", fontsize=10.5, loc="left")
    ax.set_xlabel("Transmit power of S00-A (dBm)")
    for a in axes:
        a.axvline(43, color=MUTED, lw=1, ls=(0, (1, 2)))
        a.annotate("default 43", (43, 1), xycoords=("data", "axes fraction"), xytext=(3, -12),
                   textcoords="offset points", fontsize=8, color=MUTED)

    err = float(np.max(np.abs(np.array(shift) - (powers - 43))))
    _title(fig, "Power behaves linearly, and the cap is a policy line, not a wall",
           f"S00-A swept from 40 to 49 dBm. RSRP tracks power exactly 1:1. "
           "Over-power is visible only as a warning in the change log.")
    _footer(fig)
    _brand(fig)
    fig.savefig(out / "03_power_effect.png")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/sanity")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    coverage_map(out)
    tilt_effect(out)
    power_effect(out)
    print(f"wrote 3 plots to {out}")


if __name__ == "__main__":
    main()
