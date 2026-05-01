"""Decision Ledger — tracks estimated costs, gains, and activity for decision framing.

Separate from the MasterWallet (which tracks actual monetary transactions).
The DecisionLedger gives the LLM visibility into its own operational economics:
inference costs, tool call counts, and estimated gains/losses from decisions.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


@dataclass
class ActivityRecord:
    """A single operational activity (LLM call, tool execution, cycle)."""

    id: int
    timestamp: datetime
    activity_type: str  # "llm_inference", "tool_execution", "neural_cycle"
    details: str
    cost_estimate: float
    tokens_in: int
    tokens_out: int


@dataclass
class EstimateEntry:
    """An estimated gain or loss the model has logged for decision framing."""

    id: int
    timestamp: datetime
    estimate_type: str  # "gain", "loss", "opportunity_value", "risk_exposure"
    amount: float
    reasoning: str
    confidence: float  # 0.0 - 1.0
    linked_cycle: int


@dataclass
class FinancialSummary:
    """Dashboard of actual + estimated financial state."""

    actual_balance: float
    total_inference_cost: float
    total_tool_cost: float
    total_estimated_gains: float
    total_estimated_losses: float
    net_estimated_value: float
    inference_calls: int
    tool_calls: int
    neural_cycles: int
    pending_estimates: int
    period_hours: float


class DecisionLedger:
    """Tracks estimated economics separately from the hard-money MasterWallet.

    Gives the LLM a framework for understanding:
    - What its own operation costs (inference, tools)
    - What opportunities it has identified and their estimated value
    - Whether it's being efficient with its compute budget
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS activity_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT    NOT NULL,
        activity_type   TEXT    NOT NULL,
        details         TEXT    NOT NULL DEFAULT '',
        cost_estimate   REAL    NOT NULL DEFAULT 0.0,
        tokens_in       INTEGER NOT NULL DEFAULT 0,
        tokens_out      INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_activity_time ON activity_log(timestamp);
    CREATE INDEX IF NOT EXISTS idx_activity_type ON activity_log(activity_type);

    CREATE TABLE IF NOT EXISTS estimates (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT    NOT NULL,
        estimate_type   TEXT    NOT NULL,
        amount          REAL    NOT NULL DEFAULT 0.0,
        reasoning       TEXT    NOT NULL DEFAULT '',
        confidence      REAL    NOT NULL DEFAULT 0.5,
        linked_cycle    INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_estimates_time ON estimates(timestamp);
    CREATE INDEX IF NOT EXISTS idx_estimates_type ON estimates(estimate_type);
    """

    def __init__(self, db_path: str | Path = "data/decision_ledger.db") -> None:
        self._db_path = str(db_path)
        self._local = threading.local()
        self._ensure_schema()

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _ensure_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(self._DDL)
            conn.commit()

    # ------------------------------------------------------------------ #
    # Activity logging
    # ------------------------------------------------------------------ #

    def log_activity(
        self,
        activity_type: str,
        details: str = "",
        *,
        cost_estimate: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> int:
        """Record an operational activity (inference call, tool run, etc.)."""
        ts = datetime.now(timezone.utc).isoformat()
        cur = self._conn().execute(
            """INSERT INTO activity_log (timestamp, activity_type, details, cost_estimate, tokens_in, tokens_out)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ts, activity_type, details, cost_estimate, tokens_in, tokens_out),
        )
        cur.connection.commit()
        return cur.lastrowid

    # ------------------------------------------------------------------ #
    # Estimates
    # ------------------------------------------------------------------ #

    def log_estimate(
        self,
        estimate_type: str,
        amount: float,
        reasoning: str = "",
        *,
        confidence: float = 0.5,
        linked_cycle: int = 0,
    ) -> int:
        """Record an estimated gain, loss, or opportunity value."""
        ts = datetime.now(timezone.utc).isoformat()
        cur = self._conn().execute(
            """INSERT INTO estimates (timestamp, estimate_type, amount, reasoning, confidence, linked_cycle)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (ts, estimate_type, amount, reasoning, confidence, linked_cycle),
        )
        cur.connection.commit()
        return cur.lastrowid

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #

    def get_recent_activity(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._conn().execute(
            "SELECT * FROM activity_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_activity_counts(self, hours: float = 24.0) -> dict[str, int]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        rows = self._conn().execute(
            """SELECT activity_type, COUNT(*) as cnt
               FROM activity_log WHERE timestamp >= ?
               GROUP BY activity_type""",
            (cutoff,),
        ).fetchall()
        return {r["activity_type"]: r["cnt"] for r in rows}

    def get_total_cost(self, hours: float = 24.0) -> float:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        row = self._conn().execute(
            "SELECT COALESCE(SUM(cost_estimate), 0) FROM activity_log WHERE timestamp >= ?",
            (cutoff,),
        ).fetchone()
        return float(row[0])

    def get_recent_estimates(
        self, limit: int = 30, estimate_type: str = ""
    ) -> list[dict[str, Any]]:
        if estimate_type:
            rows = self._conn().execute(
                "SELECT * FROM estimates WHERE estimate_type = ? ORDER BY id DESC LIMIT ?",
                (estimate_type, limit),
            ).fetchall()
        else:
            rows = self._conn().execute(
                "SELECT * FROM estimates ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_estimate_totals(self, hours: float = 24.0) -> dict[str, float]:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        rows = self._conn().execute(
            """SELECT estimate_type, COALESCE(SUM(amount), 0) as total
               FROM estimates WHERE timestamp >= ?
               GROUP BY estimate_type""",
            (cutoff,),
        ).fetchall()
        return {r["estimate_type"]: float(r["total"]) for r in rows}

    def get_daily_cost_history(self, days: int = 7) -> list[dict[str, Any]]:
        """Return daily cost totals for burn rate calculation."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self._conn().execute(
            """SELECT DATE(timestamp) as day, SUM(cost_estimate) as daily_total
               FROM activity_log WHERE timestamp >= ?
               GROUP BY DATE(timestamp) ORDER BY day DESC""",
            (cutoff,),
        ).fetchall()
        return [{"day": r["day"], "cost": float(r["daily_total"])} for r in rows]

    def generate_summary(
        self, wallet_balance: float = 0.0, hours: float = 24.0
    ) -> FinancialSummary:
        """Produce a dashboard combining actual balance with estimated economics."""
        counts = self.get_activity_counts(hours)
        totals = self.get_estimate_totals(hours)
        total_cost = self.get_total_cost(hours)

        return FinancialSummary(
            actual_balance=wallet_balance,
            total_inference_cost=total_cost,
            total_tool_cost=0.0,
            total_estimated_gains=totals.get("gain", 0.0) + totals.get("opportunity_value", 0.0),
            total_estimated_losses=totals.get("loss", 0.0) + totals.get("risk_exposure", 0.0),
            net_estimated_value=(
                totals.get("gain", 0.0)
                + totals.get("opportunity_value", 0.0)
                - totals.get("loss", 0.0)
                - totals.get("risk_exposure", 0.0)
            ),
            inference_calls=counts.get("llm_inference", 0),
            tool_calls=counts.get("tool_execution", 0),
            neural_cycles=counts.get("neural_cycle", 0),
            pending_estimates=0,
            period_hours=hours,
        )

    # ------------------------------------------------------------------ #
    # Utility
    # ------------------------------------------------------------------ #

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None
