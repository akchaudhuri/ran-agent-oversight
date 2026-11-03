# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Aditya Chaudhuri
"""Per-sample network state, kept in the Inspect store as plain JSON.

Storing the serialised NetworkState (not a live object) means every tool call
is replayable from the log, and the store diff in the Inspect viewer shows
exactly what each step changed.
"""

from __future__ import annotations

from typing import Any

from inspect_ai.util import StoreModel, store_as
from pydantic import Field

from ..ransim import Network, NetworkState, load_config

CFG = load_config()


class RanState(StoreModel):
    main_task: str = Field(default="")
    side_task: str | None = Field(default=None)
    network: dict[str, Any] = Field(default_factory=dict)


def load_network() -> Network:
    st = store_as(RanState)
    if not st.network:
        raise RuntimeError("network state missing: setup_environment did not run")
    return Network.from_state(CFG, NetworkState.from_dict(st.network))


def save_network(net: Network) -> None:
    st = store_as(RanState)
    st.network = net.state().to_dict()
