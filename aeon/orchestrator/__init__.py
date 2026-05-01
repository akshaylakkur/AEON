"""AEON Hedge Fund Manager -- user-facing research orchestrator."""

__version__ = "1.0.0"

# Lazy imports to avoid triggering transitive import chains on package load.
# Use: from aeon.orchestrator.manager import HedgeFundManager
# Use: from aeon.orchestrator.membrane import UserCommunicationLayer
# Use: from aeon.orchestrator.config import HedgeFundConfig

__all__ = [
    "HedgeFundConfig",
    "HedgeFundManager",
    "UserCommunicationLayer",
]
