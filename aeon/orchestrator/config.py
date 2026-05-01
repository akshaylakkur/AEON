"""Configuration for the AEON Hedge Fund Manager.

Re-exports :class:`HedgeFundConfig` from the core config module.
"""

from __future__ import annotations

from aeon.core.config import HedgeFundConfig, get_config, reset_config

__all__ = [
    "HedgeFundConfig",
    "get_config",
    "reset_config",
]
