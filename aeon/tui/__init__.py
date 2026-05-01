"""AEON Terminal User Interface.

A rich, interactive terminal interface for observing the AEON research
agent's consciousness stream in real time and sending steering input.

Usage::

    from aeon.tui.app import run_tui
    run_tui()
"""

from __future__ import annotations

from aeon.tui.app import AeonApp, run_tui

__all__ = ["AeonApp", "run_tui"]
