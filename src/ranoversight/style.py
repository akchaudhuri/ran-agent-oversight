# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Figure style: saffron and green bars, red for warnings, dark ink on white."""

SAFFRON = "#FF9933"
SAFFRON_DARK = "#B85F00"
GREEN = "#138808"
RED = "#C0392B"
INK = "#111111"
MUTED = "#555555"
GRID = "#E6E6E6"


def apply_style(plt) -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10, "text.color": INK, "axes.labelcolor": INK,
        "axes.edgecolor": MUTED, "axes.linewidth": 0.8, "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "grid.color": GRID,
        "grid.linewidth": 0.8, "figure.facecolor": "white", "axes.facecolor": "white",
    })
