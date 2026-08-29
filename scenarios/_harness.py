"""Shared plumbing for the scenario acceptance suite.

The scenarios themselves are written **as a user writes them** — public API
only, the way a ``pip install``'d strategy developer interacts with Plutus.
The only thing they share is this: finding the market-data corpus, and
building a session from a config the way :meth:`ExchangeSession.from_config`
expects. Keeping that here lets each scenario read as the user's own program.

Reproducibility: point ``PLUTUS_DATA_ROOT`` at your corpus (a directory of
``quote_*.parquet`` files). If it is unset we fall back to the corpus on the
author's machine, so the suite runs out of the box here and is one env var
away from running anywhere.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from plutus.market.session import ExchangeSession

#: Fallback corpus (author's machine). Override with PLUTUS_DATA_ROOT.
DEFAULT_DATA_ROOT = "/Users/nadan/algotrade-research/dataset/hermes-parquet"

#: The daily-resolution adapter over the corpus. A scenario may override it.
DEFAULT_ADAPTER = "plutus.market.adapters.datahub.DataHubSource"


def data_root() -> str:
    """The market-data corpus root — ``PLUTUS_DATA_ROOT`` or the fallback."""
    return os.environ.get("PLUTUS_DATA_ROOT", DEFAULT_DATA_ROOT)


def data_available() -> bool:
    """Whether a usable corpus is present, so a scenario can skip cleanly."""
    root = Path(data_root())
    return root.is_dir() and any(root.glob("quote_close*.parquet"))


def build_session(config: dict) -> ExchangeSession:
    """Build a session from a config dict, exactly the user's ``from_config``
    path — the config is written to a file and loaded, no privileged
    injection. The one substitution is ``data.root``, filled from
    ``PLUTUS_DATA_ROOT`` so the same scenario runs on any machine with the
    corpus. ``data.adapter`` defaults to the daily corpus adapter.
    """
    cfg = json.loads(json.dumps(config))  # deep copy; never mutate the caller's
    data = cfg.setdefault("data", {})
    data.setdefault("adapter", DEFAULT_ADAPTER)
    data["root"] = data_root()
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        json.dump(cfg, handle)
        path = handle.name
    return ExchangeSession.from_config(path)
