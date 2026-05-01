"""Project ÆON Simulation Engine.

Provides a controlled, deterministic environment for backtesting
strategies without risking real capital.
"""

from aeon.simulation.analyzer import SimulationAnalyzer
from aeon.simulation.clock import SimulationClock
from aeon.simulation.recorder import SimulationRecorder
from aeon.simulation.session import SimulationSession
from aeon.simulation.wallet import SimulatedWallet

__all__ = [
    "SimulationAnalyzer",
    "SimulationClock",
    "SimulationRecorder",
    "SimulationSession",
    "SimulatedWallet",
]
