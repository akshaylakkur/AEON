"""Persistent consciousness system for the AEON Hedge Fund Manager.

SQLite-backed storage that survives crashes and restarts.  Tracks research
findings, investment recommendations, user steering inputs, decisions,
thoughts, and strategic insights.

The original memories/thoughts/decisions/learnings tables are preserved.
Three new tables are added: ``findings``, ``recommendations``, and
``steering_inputs``.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Memory:
    """A single recorded event or observation."""

    id: int
    timestamp: datetime
    event_type: str
    payload: dict[str, Any]
    importance: float  # 0.0 (trivial) to 1.0 (critical)
    epoch: int  # monotonic counter for ordering


@dataclass(frozen=True, slots=True)
class ThoughtRecord:
    """A natural-language thought produced by the LLM."""

    id: int
    timestamp: datetime
    text: str
    metadata: dict[str, Any]
    importance: float


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """A decision and its eventual outcome."""

    id: int
    timestamp: datetime
    action: str
    strategy: str
    expected_roi: float
    confidence: float
    risk_score: float
    budget: float
    outcome: str | None  # "success", "failure", "partial", None if pending
    actual_return: float | None
    resolved_at: datetime | None
    notes: str


@dataclass(frozen=True, slots=True)
class StrategyStats:
    """Aggregated performance metrics for a strategy."""

    strategy_name: str
    total_trades: int
    wins: int
    losses: int
    total_pnl: float
    avg_roi: float
    win_rate: float
    avg_risk: float
    last_updated: datetime


# ---------------------------------------------------------------------------
# Consciousness
# ---------------------------------------------------------------------------


class Consciousness:
    """Persistent memory and learning system for the AEON Hedge Fund Manager.

    Parameters
    ----------
    db_path:
        Path to the SQLite database file.  Created if it doesn't exist.
    max_memories:
        Soft cap on stored memories.  Older low-importance memories are
        pruned when exceeded.
    """

    _DDL = """
    CREATE TABLE IF NOT EXISTS memories (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT    NOT NULL,
        event_type  TEXT    NOT NULL,
        payload     TEXT    NOT NULL DEFAULT '{}',
        importance  REAL    NOT NULL DEFAULT 0.5,
        epoch       INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_mem_type ON memories(event_type);
    CREATE INDEX IF NOT EXISTS idx_mem_time ON memories(timestamp);
    CREATE INDEX IF NOT EXISTS idx_mem_importance ON memories(importance);

    CREATE TABLE IF NOT EXISTS thoughts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT    NOT NULL,
        text        TEXT    NOT NULL,
        metadata    TEXT    NOT NULL DEFAULT '{}',
        importance  REAL    NOT NULL DEFAULT 0.5
    );
    CREATE INDEX IF NOT EXISTS idx_thought_time ON thoughts(timestamp);
    CREATE INDEX IF NOT EXISTS idx_thought_text ON thoughts(text);

    CREATE TABLE IF NOT EXISTS decisions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp     TEXT    NOT NULL,
        action        TEXT    NOT NULL,
        strategy      TEXT    NOT NULL DEFAULT '',
        expected_roi  REAL    NOT NULL DEFAULT 0.0,
        confidence    REAL    NOT NULL DEFAULT 0.0,
        risk_score    REAL    NOT NULL DEFAULT 0.0,
        budget        REAL    NOT NULL DEFAULT 0.0,
        outcome       TEXT,
        actual_return REAL,
        resolved_at   TEXT,
        notes         TEXT    NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_dec_strategy ON decisions(strategy);
    CREATE INDEX IF NOT EXISTS idx_dec_outcome ON decisions(outcome);

    CREATE TABLE IF NOT EXISTS strategy_performance (
        strategy_name TEXT PRIMARY KEY,
        total_trades  INTEGER NOT NULL DEFAULT 0,
        wins          INTEGER NOT NULL DEFAULT 0,
        losses        INTEGER NOT NULL DEFAULT 0,
        total_pnl     REAL    NOT NULL DEFAULT 0.0,
        avg_roi       REAL    NOT NULL DEFAULT 0.0,
        win_rate      REAL    NOT NULL DEFAULT 0.0,
        avg_risk      REAL    NOT NULL DEFAULT 0.0,
        last_updated  TEXT    NOT NULL
    );

    CREATE TABLE IF NOT EXISTS learnings (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT    NOT NULL,
        insight     TEXT    NOT NULL,
        domain      TEXT    NOT NULL DEFAULT 'general',
        confidence  REAL    NOT NULL DEFAULT 0.5,
        source      TEXT    NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_learn_domain ON learnings(domain);

    CREATE TABLE IF NOT EXISTS tool_results (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT    NOT NULL,
        tool_name   TEXT    NOT NULL,
        result      TEXT    NOT NULL DEFAULT '{}',
        success     INTEGER NOT NULL DEFAULT 1,
        cycle_id    INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_tool_time ON tool_results(timestamp);
    CREATE INDEX IF NOT EXISTS idx_tool_name ON tool_results(tool_name);

    CREATE TABLE IF NOT EXISTS findings (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT    NOT NULL,
        topic       TEXT    NOT NULL,
        finding     TEXT    NOT NULL,
        source      TEXT    NOT NULL DEFAULT '',
        importance  REAL    NOT NULL DEFAULT 0.5
    );
    CREATE INDEX IF NOT EXISTS idx_finding_topic ON findings(topic);
    CREATE INDEX IF NOT EXISTS idx_finding_time ON findings(timestamp);
    CREATE INDEX IF NOT EXISTS idx_finding_importance ON findings(importance);

    CREATE TABLE IF NOT EXISTS recommendations (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT    NOT NULL,
        topic           TEXT    NOT NULL DEFAULT '',
        asset           TEXT    NOT NULL DEFAULT '',
        direction       TEXT    NOT NULL DEFAULT '',
        thesis          TEXT    NOT NULL DEFAULT '',
        confidence      REAL    NOT NULL DEFAULT 0.0,
        evidence        TEXT    NOT NULL DEFAULT '[]',
        status          TEXT    NOT NULL DEFAULT 'sent',
        actual_return   REAL,
        outcome         TEXT,
        resolved_at     TEXT,
        metadata        TEXT    NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_rec_status ON recommendations(status);
    CREATE INDEX IF NOT EXISTS idx_rec_time ON recommendations(timestamp);
    CREATE INDEX IF NOT EXISTS idx_rec_asset ON recommendations(asset);

    CREATE TABLE IF NOT EXISTS steering_inputs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT    NOT NULL,
        input_text  TEXT    NOT NULL,
        source      TEXT    NOT NULL DEFAULT 'email'
    );
    CREATE INDEX IF NOT EXISTS idx_steer_time ON steering_inputs(timestamp);

    CREATE TABLE IF NOT EXISTS research_sessions (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp         TEXT    NOT NULL,
        session_id        INTEGER NOT NULL,
        guidance          TEXT    NOT NULL DEFAULT '',
        subtasks_json     TEXT    NOT NULL DEFAULT '[]',
        status            TEXT    NOT NULL DEFAULT 'planning',
        findings_summary  TEXT    NOT NULL DEFAULT '',
        next_plan         TEXT    NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_session_time ON research_sessions(timestamp);
    CREATE INDEX IF NOT EXISTS idx_session_status ON research_sessions(status);

    CREATE TABLE IF NOT EXISTS sent_messages (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT    NOT NULL,
        message_id  TEXT    NOT NULL,
        recipient   TEXT    NOT NULL DEFAULT '',
        subject     TEXT    NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_sent_msgid ON sent_messages(message_id);

    CREATE TABLE IF NOT EXISTS context_compactions (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp           TEXT    NOT NULL,
        sessions_compacted  INTEGER NOT NULL,
        tokens_before       INTEGER NOT NULL,
        tokens_after        INTEGER NOT NULL,
        summary             TEXT    NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_compact_time ON context_compactions(timestamp);

    CREATE TABLE IF NOT EXISTS meta (
        key   TEXT PRIMARY KEY,
        value TEXT    NOT NULL
    );
    """

    def __init__(
        self,
        db_path: str | Path = "data/consciousness.db",
        max_memories: int = 10_000,
    ) -> None:
        self._db_path = str(db_path)
        self._max_memories = max_memories
        self._local = threading.local()
        self._epoch = 0
        self._ensure_schema()
        self._load_epoch()

    # ------------------------------------------------------------------ #
    # Connection management
    # ------------------------------------------------------------------ #

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _ensure_schema(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(self._DDL)
            conn.commit()

    def _load_epoch(self) -> None:
        row = self._conn().execute(
            "SELECT value FROM meta WHERE key='epoch'"
        ).fetchone()
        if row:
            self._epoch = int(row[0])

    def _bump_epoch(self) -> int:
        self._epoch += 1
        self._conn().execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('epoch', ?)",
            (str(self._epoch),),
        ).connection.commit()
        return self._epoch

    # ------------------------------------------------------------------ #
    # Memory (event-based)
    # ------------------------------------------------------------------ #

    def remember(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        importance: float = 0.5,
    ) -> Memory:
        """Record an event in consciousness.

        Args:
            event_type: Category label (e.g. ``"research_started"``, ``"finding_stored"``).
            payload: Arbitrary JSON-serialisable context.
            importance: 0.0 (noise) to 1.0 (critical).
        """
        epoch = self._bump_epoch()
        ts = datetime.now(timezone.utc).isoformat()
        data = json.dumps(payload or {})

        cur = self._conn().execute(
            """INSERT INTO memories (timestamp, event_type, payload, importance, epoch)
               VALUES (?, ?, ?, ?, ?)""",
            (ts, event_type, data, importance, epoch),
        )
        cur.connection.commit()

        memory = Memory(
            id=cur.lastrowid,
            timestamp=datetime.fromisoformat(ts),
            event_type=event_type,
            payload=payload or {},
            importance=importance,
            epoch=epoch,
        )

        self._maybe_prune()
        return memory

    def recall(
        self,
        limit: int = 50,
        event_type: str | None = None,
        min_importance: float = 0.0,
        since: datetime | None = None,
    ) -> list[Memory]:
        """Retrieve recent memories, newest first.

        Args:
            limit: Max records to return.
            event_type: Optional filter by event category.
            min_importance: Only return memories at or above this importance.
            since: Only return memories newer than this timestamp.
        """
        clauses = ["1=1"]
        params: list[Any] = []

        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if min_importance > 0:
            clauses.append("importance >= ?")
            params.append(min_importance)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since.isoformat())

        where = " AND ".join(clauses)
        rows = self._conn().execute(
            f"""SELECT id, timestamp, event_type, payload, importance, epoch
                FROM memories
                WHERE {where}
                ORDER BY epoch DESC
                LIMIT ?""",
            (*params, limit),
        ).fetchall()

        return [
            Memory(
                id=r["id"],
                timestamp=datetime.fromisoformat(r["timestamp"]),
                event_type=r["event_type"],
                payload=json.loads(r["payload"]),
                importance=r["importance"],
                epoch=r["epoch"],
            )
            for r in rows
        ]

    def _maybe_prune(self) -> None:
        """Remove oldest low-importance memories when over the cap."""
        conn = self._conn()
        count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
        if count <= self._max_memories:
            return
        excess = count - self._max_memories + 1000  # prune in batches
        conn.execute(
            """DELETE FROM memories WHERE id IN (
                   SELECT id FROM memories
                   WHERE importance < 0.3
                   ORDER BY epoch ASC LIMIT ?
               )""",
            (excess,),
        )
        conn.commit()

    # ------------------------------------------------------------------ #
    # Thoughts (natural language, LLM-driven)
    # ------------------------------------------------------------------ #

    def store_thought(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
        importance: float = 0.5,
    ) -> ThoughtRecord:
        """Store the LLM's raw thinking output.

        Args:
            text: Natural language reasoning output from the LLM.
            metadata: Optional dict with keys like ``source``, ``model``, ``tokens``.
            importance: 0.0 (noise) to 1.0 (life-critical).
        """
        ts = datetime.now(timezone.utc).isoformat()
        meta = json.dumps(metadata or {})
        cur = self._conn().execute(
            """INSERT INTO thoughts (timestamp, text, metadata, importance)
               VALUES (?, ?, ?, ?)""",
            (ts, text, meta, importance),
        )
        cur.connection.commit()
        return ThoughtRecord(
            id=cur.lastrowid,
            timestamp=datetime.fromisoformat(ts),
            text=text,
            metadata=metadata or {},
            importance=importance,
        )

    def retrieve_relevant(
        self,
        query: str,
        limit: int = 10,
        since: datetime | None = None,
    ) -> list[ThoughtRecord]:
        """Retrieve thoughts relevant to *query* using keyword matching.

        This is a lightweight keyword-based retrieval.  A future upgrade can
        swap in vector/embedding search without changing the public API.

        Args:
            query: Search string (keywords from the LLM context).
            limit: Max records to return.
            since: Only return thoughts newer than this timestamp.
        """
        keywords = [k.lower() for k in query.split() if len(k) > 2]
        params: list[Any] = []
        clauses = ["1=1"]

        if since:
            clauses.append("timestamp >= ?")
            params.append(since.isoformat())

        where = " AND ".join(clauses)
        rows = self._conn().execute(
            f"""SELECT id, timestamp, text, metadata, importance
                FROM thoughts
                WHERE {where}
                ORDER BY timestamp DESC
                LIMIT ?""",
            (*params, limit * 5),  # over-fetch so we can rank
        ).fetchall()

        records = [
            ThoughtRecord(
                id=r["id"],
                timestamp=datetime.fromisoformat(r["timestamp"]),
                text=r["text"],
                metadata=json.loads(r["metadata"]),
                importance=r["importance"],
            )
            for r in rows
        ]

        if not keywords:
            return records[:limit]

        # Simple keyword relevance score
        def _score(record: ThoughtRecord) -> int:
            text_lower = record.text.lower()
            return sum(1 for kw in keywords if kw in text_lower)

        scored = [(r, _score(r)) for r in records]
        scored.sort(key=lambda x: (-x[1], x[0].timestamp), reverse=False)
        return [r for r, s in scored if s > 0][:limit] or records[:limit]

    def get_recent_thoughts(self, limit: int = 20) -> list[ThoughtRecord]:
        """Return the most recent stored thoughts, newest first."""
        rows = self._conn().execute(
            """SELECT id, timestamp, text, metadata, importance
               FROM thoughts
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [
            ThoughtRecord(
                id=r["id"],
                timestamp=datetime.fromisoformat(r["timestamp"]),
                text=r["text"],
                metadata=json.loads(r["metadata"]),
                importance=r["importance"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------ #
    # Decisions
    # ------------------------------------------------------------------ #

    def record_decision(
        self,
        action: str,
        strategy: str = "",
        expected_roi: float = 0.0,
        confidence: float = 0.0,
        risk_score: float = 0.0,
        budget: float = 0.0,
    ) -> int:
        """Log a decision that was made.  Returns the decision ID for later resolution."""
        ts = datetime.now(timezone.utc).isoformat()
        cur = self._conn().execute(
            """INSERT INTO decisions (timestamp, action, strategy, expected_roi,
               confidence, risk_score, budget)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ts, action, strategy, expected_roi, confidence, risk_score, budget),
        )
        cur.connection.commit()
        decision_id = cur.lastrowid
        self.remember("decision_made", {
            "decision_id": decision_id,
            "action": action,
            "strategy": strategy,
            "expected_roi": expected_roi,
            "budget": budget,
        }, importance=0.6)
        return decision_id

    def resolve_decision(
        self,
        decision_id: int,
        outcome: str,  # "success", "failure", "partial"
        actual_return: float = 0.0,
        notes: str = "",
    ) -> None:
        """Record the outcome of a previously logged decision."""
        ts = datetime.now(timezone.utc).isoformat()
        self._conn().execute(
            """UPDATE decisions SET outcome=?, actual_return=?, resolved_at=?, notes=?
               WHERE id=?""",
            (outcome, actual_return, ts, notes, decision_id),
        ).connection.commit()
        self.remember("decision_resolved", {
            "decision_id": decision_id,
            "outcome": outcome,
            "actual_return": actual_return,
        }, importance=0.5)

    def get_pending_decisions(self) -> list[DecisionRecord]:
        """Return decisions that haven't been resolved yet."""
        return self._query_decisions("WHERE outcome IS NULL")

    def get_recent_decisions(self, limit: int = 20) -> list[DecisionRecord]:
        return self._query_decisions("ORDER BY timestamp DESC LIMIT ?", (limit,))

    def _query_decisions(
        self, suffix: str, params: tuple[Any, ...] = ()
    ) -> list[DecisionRecord]:
        rows = self._conn().execute(
            f"""SELECT id, timestamp, action, strategy, expected_roi, confidence,
                       risk_score, budget, outcome, actual_return, resolved_at, notes
                FROM decisions {suffix}""",
            params,
        ).fetchall()
        return [
            DecisionRecord(
                id=r["id"],
                timestamp=datetime.fromisoformat(r["timestamp"]),
                action=r["action"],
                strategy=r["strategy"],
                expected_roi=r["expected_roi"],
                confidence=r["confidence"],
                risk_score=r["risk_score"],
                budget=r["budget"],
                outcome=r["outcome"],
                actual_return=r["actual_return"],
                resolved_at=datetime.fromisoformat(r["resolved_at"]) if r["resolved_at"] else None,
                notes=r["notes"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------ #
    # Strategy performance
    # ------------------------------------------------------------------ #

    def update_strategy_performance(
        self,
        strategy_name: str,
        *,
        is_win: bool = False,
        is_loss: bool = False,
        pnl: float = 0.0,
        roi: float = 0.0,
        risk: float = 0.0,
    ) -> StrategyStats:
        """Update aggregated stats for a strategy after a trade or action completes."""
        ts = datetime.now(timezone.utc).isoformat()
        conn = self._conn()

        existing = conn.execute(
            "SELECT * FROM strategy_performance WHERE strategy_name=?",
            (strategy_name,),
        ).fetchone()

        if existing:
            total = existing["total_trades"] + 1
            wins = existing["wins"] + (1 if is_win else 0)
            losses = existing["losses"] + (1 if is_loss else 0)
            total_pnl = existing["total_pnl"] + pnl
            avg_roi = ((existing["avg_roi"] * existing["total_trades"]) + roi) / total
            win_rate = wins / total if total > 0 else 0.0
            avg_risk = ((existing["avg_risk"] * existing["total_trades"]) + risk) / total
            conn.execute(
                """UPDATE strategy_performance SET
                       total_trades=?, wins=?, losses=?, total_pnl=?,
                       avg_roi=?, win_rate=?, avg_risk=?, last_updated=?
                   WHERE strategy_name=?""",
                (total, wins, losses, total_pnl, avg_roi, win_rate, avg_risk, ts, strategy_name),
            )
        else:
            total, wins, losses = 1, (1 if is_win else 0), (1 if is_loss else 0)
            total_pnl = pnl
            avg_roi = roi
            win_rate = wins / total
            avg_risk = risk
            conn.execute(
                """INSERT INTO strategy_performance
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (strategy_name, total, wins, losses, total_pnl, avg_roi, win_rate, avg_risk, ts),
            )
        conn.commit()

        return StrategyStats(
            strategy_name=strategy_name,
            total_trades=total,
            wins=wins,
            losses=losses,
            total_pnl=total_pnl,
            avg_roi=avg_roi,
            win_rate=win_rate,
            avg_risk=avg_risk,
            last_updated=datetime.fromisoformat(ts),
        )

    def get_strategy_performance(self, strategy_name: str) -> StrategyStats | None:
        row = self._conn().execute(
            "SELECT * FROM strategy_performance WHERE strategy_name=?",
            (strategy_name,),
        ).fetchone()
        if row is None:
            return None
        return StrategyStats(
            strategy_name=row["strategy_name"],
            total_trades=row["total_trades"],
            wins=row["wins"],
            losses=row["losses"],
            total_pnl=row["total_pnl"],
            avg_roi=row["avg_roi"],
            win_rate=row["win_rate"],
            avg_risk=row["avg_risk"],
            last_updated=datetime.fromisoformat(row["last_updated"]),
        )

    def get_all_strategy_stats(self) -> list[StrategyStats]:
        rows = self._conn().execute(
            "SELECT * FROM strategy_performance ORDER BY total_pnl DESC"
        ).fetchall()
        return [
            StrategyStats(
                strategy_name=r["strategy_name"],
                total_trades=r["total_trades"],
                wins=r["wins"],
                losses=r["losses"],
                total_pnl=r["total_pnl"],
                avg_roi=r["avg_roi"],
                win_rate=r["win_rate"],
                avg_risk=r["avg_risk"],
                last_updated=datetime.fromisoformat(r["last_updated"]),
            )
            for r in rows
        ]

    # ------------------------------------------------------------------ #
    # Learnings
    # ------------------------------------------------------------------ #

    def record_learning(
        self,
        insight: str,
        domain: str = "general",
        confidence: float = 0.5,
        source: str = "",
    ) -> None:
        """Store an insight the system has learned."""
        ts = datetime.now(timezone.utc).isoformat()
        self._conn().execute(
            """INSERT INTO learnings (timestamp, insight, domain, confidence, source)
               VALUES (?, ?, ?, ?, ?)""",
            (ts, insight, domain, confidence, source),
        ).connection.commit()
        self.remember("learning_recorded", {
            "insight": insight, "domain": domain, "confidence": confidence,
        }, importance=0.4)

    def get_learnings(
        self, domain: str | None = None, limit: int = 20
    ) -> list[dict[str, Any]]:
        if domain:
            rows = self._conn().execute(
                """SELECT timestamp, insight, domain, confidence, source
                   FROM learnings WHERE domain=? ORDER BY id DESC LIMIT ?""",
                (domain, limit),
            ).fetchall()
        else:
            rows = self._conn().execute(
                "SELECT timestamp, insight, domain, confidence, source "
                "FROM learnings ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Research Findings (NEW)
    # ------------------------------------------------------------------ #

    def store_finding(
        self,
        topic: str,
        finding: str,
        source: str = "",
        importance: float = 0.5,
    ) -> int:
        """Store a research finding.

        Args:
            topic: The research topic or asset being investigated.
            finding: The finding text (natural language).
            source: Where the finding came from (URL, tool name, etc.).
            importance: 0.0 (trivial) to 1.0 (critical).

        Returns:
            The finding's database ID.
        """
        ts = datetime.now(timezone.utc).isoformat()
        cur = self._conn().execute(
            """INSERT INTO findings (timestamp, topic, finding, source, importance)
               VALUES (?, ?, ?, ?, ?)""",
            (ts, topic, finding, source, importance),
        )
        cur.connection.commit()
        finding_id = cur.lastrowid

        self.remember("finding_stored", {
            "finding_id": finding_id,
            "topic": topic,
            "source": source,
            "importance": importance,
        }, importance=min(importance, 0.7))

        return finding_id

    def recall_findings(
        self,
        query: str,
        limit: int = 20,
        min_importance: float = 0.0,
        since: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Search past findings by topic keyword matching.

        Args:
            query: Search string (keywords).
            limit: Max results to return.
            min_importance: Minimum importance threshold.
            since: Only return findings newer than this timestamp.

        Returns:
            A list of finding dicts, ranked by relevance then recency.
        """
        clauses = ["1=1"]
        params: list[Any] = []

        if min_importance > 0:
            clauses.append("importance >= ?")
            params.append(min_importance)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since.isoformat())

        where = " AND ".join(clauses)
        rows = self._conn().execute(
            f"""SELECT id, timestamp, topic, finding, source, importance
                FROM findings
                WHERE {where}
                ORDER BY timestamp DESC
                LIMIT ?""",
            (*params, limit * 5),  # over-fetch for ranking
        ).fetchall()

        results = [dict(r) for r in rows]

        # Keyword relevance ranking
        keywords = [k.lower() for k in query.split() if len(k) > 2]
        if not keywords:
            return results[:limit]

        def _score(row: dict[str, Any]) -> int:
            text = f"{row['topic']} {row['finding']}".lower()
            return sum(1 for kw in keywords if kw in text)

        scored = [(r, _score(r)) for r in results]
        scored.sort(key=lambda x: (-x[1], x[0]["timestamp"]), reverse=False)
        ranked = [r for r, s in scored if s > 0]
        return ranked[:limit] if ranked else results[:limit]

    def get_recent_findings(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return the most recent findings, newest first."""
        rows = self._conn().execute(
            """SELECT id, timestamp, topic, finding, source, importance
               FROM findings
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Investment Recommendations (NEW)
    # ------------------------------------------------------------------ #

    def store_recommendation(self, recommendation: dict[str, Any]) -> int:
        """Store an investment recommendation sent to the user.

        Args:
            recommendation: Dict with keys like ``topic``, ``asset``,
                ``direction`` (buy/sell/hold), ``thesis``, ``confidence``,
                ``evidence`` (list of strings), ``metadata`` (dict).

        Returns:
            The recommendation's database ID.
        """
        ts = datetime.now(timezone.utc).isoformat()
        cur = self._conn().execute(
            """INSERT INTO recommendations
               (timestamp, topic, asset, direction, thesis, confidence,
                evidence, status, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                ts,
                recommendation.get("topic", ""),
                recommendation.get("asset", ""),
                recommendation.get("direction", ""),
                recommendation.get("thesis", ""),
                recommendation.get("confidence", 0.0),
                json.dumps(recommendation.get("evidence", [])),
                recommendation.get("status", "sent"),
                json.dumps(recommendation.get("metadata", {})),
            ),
        )
        cur.connection.commit()
        rec_id = cur.lastrowid

        self.remember("recommendation_sent", {
            "rec_id": rec_id,
            "asset": recommendation.get("asset", ""),
            "direction": recommendation.get("direction", ""),
            "confidence": recommendation.get("confidence", 0.0),
        }, importance=0.8)

        return rec_id

    def get_recommendations(
        self,
        limit: int = 50,
        status: str | None = None,
        asset: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get past investment recommendations.

        Args:
            limit: Max results.
            status: Filter by status (``"sent"``, ``"confirmed"``, ``"rejected"``).
            asset: Filter by asset symbol.

        Returns:
            List of recommendation dicts, newest first.
        """
        clauses = ["1=1"]
        params: list[Any] = []

        if status:
            clauses.append("status = ?")
            params.append(status)
        if asset:
            clauses.append("asset = ?")
            params.append(asset)

        where = " AND ".join(clauses)
        rows = self._conn().execute(
            f"""SELECT id, timestamp, topic, asset, direction, thesis,
                       confidence, evidence, status, actual_return, outcome,
                       resolved_at, metadata
                FROM recommendations
                WHERE {where}
                ORDER BY timestamp DESC
                LIMIT ?""",
            (*params, limit),
        ).fetchall()

        results = []
        for r in rows:
            rec = dict(r)
            rec["evidence"] = json.loads(rec["evidence"])
            rec["metadata"] = json.loads(rec["metadata"])
            results.append(rec)
        return results

    def update_recommendation_outcome(
        self,
        rec_id: int,
        outcome: str,
        actual_return: float | None = None,
    ) -> None:
        """Track the outcome of a past recommendation.

        Args:
            rec_id: The recommendation's database ID.
            outcome: Result description (e.g. ``"profit"``, ``"loss"``, ``"neutral"``).
            actual_return: The actual percentage return, if known.
        """
        ts = datetime.now(timezone.utc).isoformat()
        self._conn().execute(
            """UPDATE recommendations
               SET outcome=?, actual_return=?, resolved_at=?
               WHERE id=?""",
            (outcome, actual_return, ts, rec_id),
        ).connection.commit()

        self.remember("recommendation_resolved", {
            "rec_id": rec_id,
            "outcome": outcome,
            "actual_return": actual_return,
        }, importance=0.6)

    def update_recommendation_status(self, rec_id: int, status: str) -> None:
        """Update the status of a recommendation.

        Args:
            rec_id: The recommendation's database ID.
            status: New status (``"sent"``, ``"confirmed"``, ``"rejected"``).
        """
        self._conn().execute(
            "UPDATE recommendations SET status=? WHERE id=?",
            (status, rec_id),
        ).connection.commit()

    # ------------------------------------------------------------------ #
    # Steering Inputs (NEW)
    # ------------------------------------------------------------------ #

    def store_steering_input(
        self,
        input_text: str,
        timestamp: datetime | None = None,
        source: str = "email",
    ) -> int:
        """Store a user steering input.

        Args:
            input_text: The user's guidance text.
            timestamp: When the input was received (defaults to now).
            source: Where the input came from (``"email"``, ``"cli"``, etc.).

        Returns:
            The steering input's database ID.
        """
        ts = (timestamp or datetime.now(timezone.utc)).isoformat()
        cur = self._conn().execute(
            """INSERT INTO steering_inputs (timestamp, input_text, source)
               VALUES (?, ?, ?)""",
            (ts, input_text, source),
        )
        cur.connection.commit()
        steer_id = cur.lastrowid

        self.remember("steering_received", {
            "steer_id": steer_id,
            "source": source,
            "text_preview": input_text[:200],
        }, importance=0.9)

        return steer_id

    def get_latest_steering(self) -> str | None:
        """Get the most recent user steering input text.

        Returns:
            The steering text, or ``None`` if no steering has been received.
        """
        row = self._conn().execute(
            "SELECT input_text FROM steering_inputs ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return row["input_text"] if row else None

    def get_steering_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent steering inputs, newest first."""
        rows = self._conn().execute(
            """SELECT id, timestamp, input_text, source
               FROM steering_inputs
               ORDER BY timestamp DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ #
    # Sent Messages (for IMAP reply verification)
    # ------------------------------------------------------------------ #

    def store_sent_message(
        self,
        message_id: str,
        recipient: str,
        subject: str,
        timestamp: datetime | None = None,
    ) -> int:
        """Record a sent email's Message-ID for reply verification."""
        ts = (timestamp or datetime.now(timezone.utc)).isoformat()
        cur = self._conn().execute(
            """INSERT INTO sent_messages (timestamp, message_id, recipient, subject)
               VALUES (?, ?, ?, ?)""",
            (ts, message_id, recipient, subject),
        )
        cur.connection.commit()
        return cur.lastrowid

    def is_reply_to_sent_message(self, in_reply_to: str) -> bool:
        """Check if an In-Reply-To header matches a message we sent."""
        if not in_reply_to:
            return False
        row = self._conn().execute(
            "SELECT 1 FROM sent_messages WHERE message_id = ? LIMIT 1",
            (in_reply_to.strip(),),
        ).fetchone()
        return row is not None

    # ------------------------------------------------------------------ #
    # Research Summary (NEW)
    # ------------------------------------------------------------------ #

    def get_research_summary(self, hours: int = 24) -> dict[str, Any]:
        """Produce a summary of recent research activity.

        Args:
            hours: Look back this many hours.

        Returns:
            A dict with counts and highlights of recent activity.
        """
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        conn = self._conn()

        findings_count = conn.execute(
            "SELECT COUNT(*) FROM findings WHERE timestamp >= ?", (since,)
        ).fetchone()[0]

        recs_count = conn.execute(
            "SELECT COUNT(*) FROM recommendations WHERE timestamp >= ?", (since,)
        ).fetchone()[0]

        thoughts_count = conn.execute(
            "SELECT COUNT(*) FROM thoughts WHERE timestamp >= ?", (since,)
        ).fetchone()[0]

        tool_calls_count = conn.execute(
            "SELECT COUNT(*) FROM tool_results WHERE timestamp >= ?", (since,)
        ).fetchone()[0]

        top_findings = conn.execute(
            """SELECT topic, finding, importance
               FROM findings WHERE timestamp >= ?
               ORDER BY importance DESC LIMIT 5""",
            (since,),
        ).fetchall()

        recent_recs = conn.execute(
            """SELECT asset, direction, confidence, status
               FROM recommendations WHERE timestamp >= ?
               ORDER BY timestamp DESC LIMIT 5""",
            (since,),
        ).fetchall()

        latest_steering = self.get_latest_steering()

        return {
            "period_hours": hours,
            "findings_count": findings_count,
            "recommendations_count": recs_count,
            "thoughts_count": thoughts_count,
            "tool_calls_count": tool_calls_count,
            "top_findings": [dict(r) for r in top_findings],
            "recent_recommendations": [dict(r) for r in recent_recs],
            "latest_steering": latest_steering,
        }

    # ------------------------------------------------------------------ #
    # Context generation (for LLM consumption)
    # ------------------------------------------------------------------ #

    def generate_context_prompt(self) -> str:
        """Produce a structured summary the LLM can use as context.

        Returns recent activity, research findings, recommendations,
        strategy performance, and user steering as a machine-readable summary.
        """
        recent = self.recall(limit=30, min_importance=0.3)
        strategies = self.get_all_strategy_stats()
        decisions = self.get_recent_decisions(limit=10)
        learnings = self.get_learnings(limit=5)
        recent_thoughts = self.get_recent_thoughts(limit=5)
        recent_findings = self.get_recent_findings(limit=10)
        recent_recs = self.get_recommendations(limit=5)
        latest_steering = self.get_latest_steering()

        parts: list[str] = []

        # User steering (most important context)
        if latest_steering:
            parts.append("## User Steering")
            parts.append(f"Latest guidance: {latest_steering}")

        # Recent findings
        if recent_findings:
            parts.append("\n## Recent Research Findings")
            for f in recent_findings[:10]:
                parts.append(
                    f"- [{f['topic']}] {f['finding'][:200]} "
                    f"(importance: {f['importance']:.1f}, source: {f['source']})"
                )

        # Recent recommendations
        if recent_recs:
            parts.append("\n## Recent Recommendations")
            for rec in recent_recs:
                parts.append(
                    f"- {rec['asset']} {rec['direction']} "
                    f"(confidence: {rec['confidence']:.0%}, status: {rec['status']})"
                )

        # Recent timeline
        if recent:
            parts.append("\n## Recent Activity")
            for m in recent[:15]:
                ts = m.timestamp.strftime("%H:%M:%S")
                summary = m.event_type
                if m.payload:
                    highlights = {k: v for k, v in m.payload.items()
                                  if k in ("action", "strategy", "outcome", "amount",
                                            "asset", "topic", "domain", "cause",
                                            "direction", "confidence")}
                    if highlights:
                        summary += f" | {highlights}"
                parts.append(f"- [{ts}] {summary}")

        # Strategy performance
        if strategies:
            parts.append("\n## Strategy Performance")
            for s in strategies:
                parts.append(
                    f"- **{s.strategy_name}**: {s.total_trades} trades, "
                    f"{s.win_rate:.0%} win rate, "
                    f"P&L ${s.total_pnl:+.2f}, "
                    f"avg ROI {s.avg_roi:+.2%}"
                )

        # Pending decisions
        pending = self.get_pending_decisions()
        if pending:
            parts.append("\n## Pending Decisions")
            for d in pending:
                parts.append(
                    f"- [{d.id}] {d.action} ({d.strategy}) -- "
                    f"expected ROI {d.expected_roi:+.2%}, budget ${d.budget:.2f}"
                )

        # Recent learnings
        if learnings:
            parts.append("\n## Key Learnings")
            for l_item in learnings[:5]:
                parts.append(f"- [{l_item['domain']}] {l_item['insight']}")

        # Recent LLM thoughts
        if recent_thoughts:
            parts.append("\n## Recent Thoughts")
            for t in recent_thoughts[:5]:
                parts.append(f"- [{t.timestamp.strftime('%H:%M:%S')}] {t.text[:200]}")

        return "\n".join(parts) if parts else "No significant context accumulated yet."

    # ------------------------------------------------------------------ #
    # Tool results
    # ------------------------------------------------------------------ #

    def store_tool_result(
        self,
        tool_name: str,
        result: Any,
        *,
        success: bool = True,
        cycle_id: int = 0,
    ) -> int:
        """Persist a tool execution result for context building."""
        ts = datetime.now(timezone.utc).isoformat()
        result_str = json.dumps(result, default=str)
        cur = self._conn().execute(
            """INSERT INTO tool_results (timestamp, tool_name, result, success, cycle_id)
               VALUES (?, ?, ?, ?, ?)""",
            (ts, tool_name, result_str, 1 if success else 0, cycle_id),
        )
        cur.connection.commit()
        return cur.lastrowid

    def get_recent_tool_results(
        self, limit: int = 20, tool_name: str | None = None
    ) -> list[dict[str, Any]]:
        """Retrieve recent tool results, newest first."""
        if tool_name:
            rows = self._conn().execute(
                """SELECT timestamp, tool_name, result, success, cycle_id
                   FROM tool_results WHERE tool_name = ?
                   ORDER BY id DESC LIMIT ?""",
                (tool_name, limit),
            ).fetchall()
        else:
            rows = self._conn().execute(
                """SELECT timestamp, tool_name, result, success, cycle_id
                   FROM tool_results ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [
            {
                "timestamp": r["timestamp"],
                "tool_name": r["tool_name"],
                "result": json.loads(r["result"]),
                "success": bool(r["success"]),
                "cycle_id": r["cycle_id"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------------ #
    # Research Sessions
    # ------------------------------------------------------------------ #

    def store_session(self, session: dict[str, Any]) -> int:
        """Persist a research session plan and its outcome."""
        ts = datetime.now(timezone.utc).isoformat()
        subtasks = json.dumps(session.get("subtasks", []), default=str)
        cur = self._conn().execute(
            """INSERT INTO research_sessions
               (timestamp, session_id, guidance, subtasks_json, status,
                findings_summary, next_plan)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                ts,
                session.get("session_id", 0),
                session.get("guidance", ""),
                subtasks,
                session.get("status", "planning"),
                session.get("findings_summary", ""),
                session.get("next_plan", ""),
            ),
        )
        cur.connection.commit()
        return cur.lastrowid

    def update_session(self, row_id: int, **fields: Any) -> None:
        """Update fields on an existing session row."""
        allowed = {"status", "findings_summary", "next_plan", "subtasks_json"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        set_clause = ", ".join(f"{k}=?" for k in updates)
        self._conn().execute(
            f"UPDATE research_sessions SET {set_clause} WHERE id=?",
            (*updates.values(), row_id),
        ).connection.commit()

    def get_recent_sessions(self, limit: int = 5) -> list[dict[str, Any]]:
        """Return recent research sessions, newest first."""
        rows = self._conn().execute(
            "SELECT * FROM research_sessions ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["subtasks_json"] = json.loads(d["subtasks_json"])
            results.append(d)
        return results

    def get_last_session_plan(self) -> str | None:
        """Return the next_plan from the most recent completed session."""
        row = self._conn().execute(
            "SELECT next_plan FROM research_sessions "
            "WHERE status='completed' AND next_plan != '' "
            "ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        return row["next_plan"] if row else None

    # ------------------------------------------------------------------ #
    # Utility
    # ------------------------------------------------------------------ #

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate statistics about the consciousness store."""
        conn = self._conn()
        return {
            "total_memories": conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0],
            "total_thoughts": conn.execute("SELECT COUNT(*) FROM thoughts").fetchone()[0],
            "total_decisions": conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0],
            "total_learnings": conn.execute("SELECT COUNT(*) FROM learnings").fetchone()[0],
            "total_findings": conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0],
            "total_recommendations": conn.execute("SELECT COUNT(*) FROM recommendations").fetchone()[0],
            "total_steering_inputs": conn.execute("SELECT COUNT(*) FROM steering_inputs").fetchone()[0],
            "total_sessions": conn.execute("SELECT COUNT(*) FROM research_sessions").fetchone()[0],
            "strategies_tracked": conn.execute(
                "SELECT COUNT(*) FROM strategy_performance"
            ).fetchone()[0],
            "db_path": self._db_path,
            "db_size_kb": round(Path(self._db_path).stat().st_size / 1024, 1)
            if Path(self._db_path).exists() else 0,
        }

    def close(self) -> None:
        """Close the database connection for the current thread."""
        conn = getattr(self._local, "conn", None)
        if conn:
            conn.close()
            self._local.conn = None
