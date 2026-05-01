"""Simulation connectors — real-world data, simulated money.

These wrappers let AEON test strategies against real data and APIs
without risking capital. Every action is tagged as simulated and
recorded for later analysis.
"""

from __future__ import annotations

from aeon.simulation.connectors.commerce import CommerceSimulator
from aeon.simulation.connectors.cost_estimator import CostEstimator
from aeon.simulation.connectors.dataclasses import SimulatedData
from aeon.simulation.connectors.market_data import MarketDataSimulator
from aeon.simulation.connectors.web_research import WebResearchSimulator

__all__ = [
    "SimulatedData",
    "MarketDataSimulator",
    "WebResearchSimulator",
    "CommerceSimulator",
    "CostEstimator",
]
