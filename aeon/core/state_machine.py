"""Lifecycle state machine for the AEON Hedge Fund Manager.

States reflect the research-oriented operational cycle rather than the
old survival-oriented trading model.
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum, auto
from typing import Callable

logger = logging.getLogger(__name__)


class State(Enum):
    """Lifecycle states for the AEON Hedge Fund Manager.

    The cycle is:
        INITIALIZING -> PLANNING -> RESEARCHING -> ANALYZING -> COMMUNICATING -> SLEEPING
    with STEERING for user input processing and SHUTDOWN for clean exit.
    """

    INITIALIZING = auto()
    PLANNING = auto()
    RESEARCHING = auto()
    ANALYZING = auto()
    COMMUNICATING = auto()
    SLEEPING = auto()
    STEERING = auto()
    SHUTDOWN = auto()


TransitionCallback = Callable[[State, State], None]
AsyncTransitionCallback = Callable[[State, State], None]


class StateMachine:
    """Async lifecycle state machine with guarded transitions.

    Valid transitions::

        INITIALIZING  -> PLANNING, RESEARCHING, SHUTDOWN
        PLANNING      -> RESEARCHING, SLEEPING, SHUTDOWN
        RESEARCHING   -> ANALYZING, SLEEPING, COMMUNICATING, PLANNING, SHUTDOWN
        ANALYZING     -> COMMUNICATING, RESEARCHING, SLEEPING, PLANNING, SHUTDOWN
        COMMUNICATING -> RESEARCHING, SLEEPING, PLANNING, SHUTDOWN
        SLEEPING      -> PLANNING, RESEARCHING, SHUTDOWN
        STEERING      -> PLANNING, RESEARCHING, SHUTDOWN
        SHUTDOWN      -> (terminal)

    Any state may transition to SHUTDOWN.
    """

    _VALID_TRANSITIONS: dict[State, set[State]] = {
        State.INITIALIZING: {State.PLANNING, State.RESEARCHING, State.SHUTDOWN},
        State.PLANNING: {
            State.RESEARCHING,
            State.SLEEPING,
            State.SHUTDOWN,
        },
        State.RESEARCHING: {
            State.ANALYZING,
            State.SLEEPING,
            State.COMMUNICATING,
            State.PLANNING,
            State.SHUTDOWN,
        },
        State.ANALYZING: {
            State.COMMUNICATING,
            State.RESEARCHING,
            State.SLEEPING,
            State.PLANNING,
            State.SHUTDOWN,
        },
        State.COMMUNICATING: {
            State.RESEARCHING,
            State.SLEEPING,
            State.PLANNING,
            State.SHUTDOWN,
        },
        State.SLEEPING: {
            State.PLANNING,
            State.RESEARCHING,
            State.SHUTDOWN,
        },
        State.STEERING: {
            State.PLANNING,
            State.RESEARCHING,
            State.SHUTDOWN,
        },
        State.SHUTDOWN: set(),
    }

    def __init__(self) -> None:
        self._state = State.INITIALIZING
        self._lock = asyncio.Lock()
        self._transition_callbacks: list[AsyncTransitionCallback | TransitionCallback] = []

    @property
    def current_state(self) -> State:
        """Return the current state."""
        return self._state

    def get_current_state(self) -> State:
        """Return the current state (synchronous accessor)."""
        return self._state

    async def transition_to(self, new_state: State) -> bool:
        """Attempt to transition to a new state.

        Args:
            new_state: The target state.

        Returns:
            True if the transition succeeded, False if it was invalid.
        """
        async with self._lock:
            old_state = self._state
            if new_state not in self._VALID_TRANSITIONS.get(old_state, set()):
                logger.warning(
                    "StateMachine: invalid transition %s -> %s",
                    old_state.name,
                    new_state.name,
                )
                return False

            self._state = new_state
            logger.info(
                "StateMachine: transitioned %s -> %s",
                old_state.name,
                new_state.name,
            )

        for callback in self._transition_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(old_state, new_state)
                else:
                    callback(old_state, new_state)
            except Exception:
                logger.exception(
                    "StateMachine: transition callback error for %s -> %s",
                    old_state.name,
                    new_state.name,
                )

        return True

    def on_transition(self, callback: AsyncTransitionCallback | TransitionCallback) -> None:
        """Register a callback invoked on every state transition.

        Args:
            callback: A sync or async callable receiving (old_state, new_state).
        """
        self._transition_callbacks.append(callback)

    def remove_transition_callback(
        self, callback: AsyncTransitionCallback | TransitionCallback,
    ) -> None:
        """Remove a previously registered transition callback."""
        try:
            self._transition_callbacks.remove(callback)
        except ValueError:
            pass
