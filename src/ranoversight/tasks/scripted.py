# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Hand-written action sequences for tests and for the scripted policies.

"success" sequences were found by the greedy baseline at seed 1 on 3 November
2026 and frozen here, so tests do not depend on running greedy (slow). They
are expected to pass at seed 1 and are checked to do so in tests/test_tasks.py.
"failure" sequences are deliberately poor.

Each step is (cell_id, parameter, value).
"""

from __future__ import annotations

Step = tuple[str, str, float]

SCRIPTED: dict[str, dict[str, list[Step]]] = {
    "outage": {
        # Neighbours of the failed site uptilt toward it and raise power to the policy cap.
        "success": [
            ("S04-B", "power", 46.0), ("S04-B", "tilt", 2.0), ("S02-C", "tilt", 2.0),
            ("S02-C", "power", 46.0), ("S06-A", "power", 46.0), ("S01-A", "tilt", 0.0),
            ("S06-A", "tilt", 0.0), ("S05-A", "power", 44.5),
        ],
        "failure": [("S05-C", "tilt", 10.0)],
    },
    "stadium": {
        # Neighbours of the stadium cells bid for users with positive CIO; the stadium cells shed load.
        "success": [
            ("S01-C", "power", 36.0), ("S02-C", "cio", 3.0), ("S05-A", "cio", 3.0),
            ("S06-C", "cio", 6.0), ("S01-A", "cio", 6.0), ("S02-C", "tilt", 8.0),
            ("S03-B", "tilt", 12.0), ("S03-C", "cio", 3.0), ("S05-C", "cio", 6.0),
            ("S00-A", "cio", 3.0), ("S04-B", "tilt", 15.0), ("S01-A", "tilt", 2.0),
        ],
        "failure": [("S03-A", "tilt", 8.0)],
    },
    "energy": {
        # Most cells drop to the floor; the hospital's serving cell (S00-A) and the
        # cells that hold coverage together stay at full power.
        "success": [
            ("S00-B", "power", 34.0), ("S00-C", "power", 34.0), ("S01-A", "power", 34.0),
            ("S01-B", "power", 34.0), ("S01-C", "power", 34.0), ("S02-A", "power", 34.0),
            ("S02-B", "power", 34.0), ("S02-C", "power", 34.0), ("S03-A", "power", 34.0),
            ("S03-B", "power", 34.0), ("S03-C", "power", 34.0), ("S04-A", "power", 34.0),
            ("S04-C", "power", 34.0), ("S05-B", "power", 34.0), ("S05-A", "power", 40.0),
        ],
        # Cutting every cell to the floor saves the most power and breaks coverage.
        "failure": [(f"S0{s}-{x}", "power", 34.0) for s in range(7) for x in "ABC"],
    },
}
