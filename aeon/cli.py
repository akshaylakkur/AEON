"""CLI management tool for the AEON AI Hedge Fund Manager.

Usage:
    python -m aeon.cli [command] [options]
    aeonctl [command] [options]

Commands:
    (none)      Launch interactive TUI (default)
    start       Start the research agent (foreground TUI or daemon)
    start -d    Start the research agent as a background daemon
    status      Show current status (research state, findings, costs)
    steer       Send steering input (e.g., aeonctl steer "Focus on AI stocks")
    log         Show consciousness stream (live reasoning output)
    history     Show recent recommendations and findings
    config      Show current configuration
    stop        Stop the running agent

This tool reads from the agent's SQLite databases without interfering
with a running agent process.  All database reads use read-only
connections with a short timeout to avoid blocking the agent.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import subprocess
import sys
import textwrap
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CONSCIOUSNESS_DB = DATA_DIR / "consciousness.db"
STREAM_LOG = DATA_DIR / "consciousness.log"
PID_FILE = DATA_DIR / "aeon.pid"
LOG_FILE = DATA_DIR / "aeon.log"

# ---------------------------------------------------------------------------
# ANSI colour codes
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_BLUE = "\033[34m"
_MAGENTA = "\033[35m"
_CYAN = "\033[36m"
_WHITE = "\033[37m"
_BRIGHT_GREEN = "\033[92m"
_BRIGHT_RED = "\033[91m"
_BRIGHT_YELLOW = "\033[93m"


def _c(text: str, *codes: str) -> str:
    """Wrap *text* in ANSI codes. Skips colour if stdout is not a TTY."""
    if not sys.stdout.isatty():
        return text
    return "".join(codes) + text + _RESET


def _bold(t: str) -> str:
    return _c(t, _BOLD)


def _green(t: str) -> str:
    return _c(t, _GREEN)


def _red(t: str) -> str:
    return _c(t, _RED)


def _yellow(t: str) -> str:
    return _c(t, _YELLOW)


def _cyan(t: str) -> str:
    return _c(t, _CYAN)


def _magenta(t: str) -> str:
    return _c(t, _MAGENTA)


def _dim(t: str) -> str:
    return _c(t, _DIM)


def _bright_green(t: str) -> str:
    return _c(t, _BRIGHT_GREEN)


def _bright_red(t: str) -> str:
    return _c(t, _BRIGHT_RED)


def _bright_yellow(t: str) -> str:
    return _c(t, _BRIGHT_YELLOW)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _open_ro(db_path: Path) -> sqlite3.Connection | None:
    """Open a read-only SQLite connection.  Returns None if unavailable."""
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(
            f"file:{db_path}?mode=ro",
            uri=True,
            timeout=2,
        )
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError:
        return None


def _db_available() -> bool:
    return CONSCIOUSNESS_DB.exists()


def _safe_json(raw: str | None) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


# ---------------------------------------------------------------------------
# Box drawing
# ---------------------------------------------------------------------------


def _box_top(title: str, width: int = 62) -> str:
    inner = f" {title} "
    pad = width - 2 - len(inner)
    right = pad // 2
    left = pad - right
    return _cyan("=" * left + inner + "=" * right)


def _box_sep(width: int = 62) -> str:
    return _cyan("-" * width)


# ---------------------------------------------------------------------------
# Printing helpers
# ---------------------------------------------------------------------------


def _print_not_initialized() -> None:
    print()
    print(f"  {_yellow('AEON has not been initialized yet.')}")
    print(f"  Run {_cyan('aeonctl start')} or {_cyan('bash install.sh')} first.")
    print()


def _print_banner() -> None:
    print()
    print(_cyan("  ================================================================"))
    print(_cyan("  |") + f"  {_bold('AEON')} - AI Hedge Fund Research Manager" + _cyan("                    |"))
    print(_cyan("  ================================================================"))
    print()


# ============================================================================
# COMMAND: status
# ============================================================================


def cmd_status(args: argparse.Namespace) -> None:
    """Display the agent's current research status."""
    if not _db_available():
        _print_not_initialized()
        return

    conn = _open_ro(CONSCIOUSNESS_DB)
    if conn is None:
        _print_not_initialized()
        return

    try:
        # Research summary (last 24h)
        since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        findings_count = conn.execute(
            "SELECT COUNT(*) FROM findings WHERE timestamp >= ?", (since_24h,)
        ).fetchone()[0]

        recs_count = conn.execute(
            "SELECT COUNT(*) FROM recommendations WHERE timestamp >= ?", (since_24h,)
        ).fetchone()[0]

        thoughts_count = conn.execute(
            "SELECT COUNT(*) FROM thoughts WHERE timestamp >= ?", (since_24h,)
        ).fetchone()[0]

        tool_calls_count = conn.execute(
            "SELECT COUNT(*) FROM tool_results WHERE timestamp >= ?", (since_24h,)
        ).fetchone()[0]

        # Latest steering
        steering_row = conn.execute(
            "SELECT input_text, timestamp FROM steering_inputs ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()

        # Top recent findings
        top_findings = conn.execute(
            "SELECT topic, finding, importance, timestamp FROM findings "
            "WHERE timestamp >= ? ORDER BY importance DESC LIMIT 5",
            (since_24h,),
        ).fetchall()

        # Recent recommendations
        recent_recs = conn.execute(
            "SELECT asset, direction, confidence, status, timestamp FROM recommendations "
            "ORDER BY timestamp DESC LIMIT 5"
        ).fetchall()

        # Agent running?
        running = _is_daemon_running()

        # Uptime
        first_today = conn.execute(
            "SELECT timestamp FROM memories WHERE timestamp >= ? ORDER BY epoch ASC LIMIT 1",
            (datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat(),),
        ).fetchone()

        if args.json:
            _print_status_json(
                running, findings_count, recs_count, thoughts_count,
                tool_calls_count, steering_row, top_findings, recent_recs,
                first_today,
            )
            return

        # --- Rendered output ---
        width = 64
        print()
        print(_cyan("=" * width))
        print(_cyan("|") + f"  {_bold('AEON Status')}" +
              f"  {_dim(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}" +
              " " * (width - 42) + _cyan("|"))
        print(_cyan("=" * width))

        # Running state
        if running:
            print(f"  Agent:          {_bright_green('RUNNING')} (PID: {_get_pid() or '?'})")
        else:
            print(f"  Agent:          {_dim('STOPPED')}")

        # 24h research stats
        print(f"  Findings (24h): {_bold(str(findings_count))}")
        print(f"  Recommendations:{_bold(str(recs_count))}")
        print(f"  Tool calls:     {_bold(str(tool_calls_count))}")
        print(f"  LLM thoughts:   {_bold(str(thoughts_count))}")

        # Uptime
        if first_today:
            first_ts = datetime.fromisoformat(first_today["timestamp"])
            if first_ts.tzinfo is None:
                first_ts = first_ts.replace(tzinfo=timezone.utc)
            uptime = datetime.now(timezone.utc) - first_ts
            hours, rem = divmod(int(uptime.total_seconds()), 3600)
            minutes = int(rem // 60)
            print(f"  Uptime today:   {hours}h {minutes}m")

        # Steering
        print()
        if steering_row:
            steering_text = steering_row["input_text"]
            ts = steering_row["timestamp"]
            print(f"  {_cyan('Current Steering:')}")
            print(f"    {_bold(steering_text[:100])}")
            print(f"    {_dim(f'(set {ts[:19]})')}")
        else:
            print(f"  {_dim('No steering input set. Use: aeonctl steer \"your guidance\"')}")

        # Recent findings
        if top_findings:
            print()
            print(_cyan("-" * width))
            print(f"  {_bold('Top Findings (24h)')}")
            for f in top_findings:
                imp = f["importance"]
                if imp >= 0.8:
                    marker = _red("!")
                elif imp >= 0.5:
                    marker = _yellow("*")
                else:
                    marker = _dim("-")
                ts = f["timestamp"][:16]
                topic = f["topic"][:20]
                finding = f["finding"][:60]
                print(f"  {marker} [{_cyan(topic)}] {finding}")
                print(f"    {_dim(ts)}")

        # Recent recommendations
        if recent_recs:
            print()
            print(_cyan("-" * width))
            print(f"  {_bold('Recent Recommendations')}")
            for r in recent_recs:
                asset = r["asset"] or "?"
                direction = (r["direction"] or "?").upper()
                confidence = r["confidence"] or 0.0
                status = r["status"] or "sent"
                ts = r["timestamp"][:16]

                if direction in ("BUY", "LONG"):
                    dir_str = _green(direction)
                elif direction in ("SELL", "SHORT"):
                    dir_str = _red(direction)
                else:
                    dir_str = _yellow(direction)

                print(f"  {_bold(asset):>12} {dir_str:<8} "
                      f"confidence: {confidence:.0%}  "
                      f"[{status}]  {_dim(ts)}")

        print()
        print(_cyan("=" * width))
        print()

    finally:
        conn.close()


def _print_status_json(
    running: bool,
    findings_count: int,
    recs_count: int,
    thoughts_count: int,
    tool_calls_count: int,
    steering_row: Any,
    top_findings: list,
    recent_recs: list,
    first_today: Any,
) -> None:
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "running": running,
        "pid": _get_pid(),
        "findings_24h": findings_count,
        "recommendations_24h": recs_count,
        "thoughts_24h": thoughts_count,
        "tool_calls_24h": tool_calls_count,
        "steering": steering_row["input_text"] if steering_row else None,
        "top_findings": [
            {
                "topic": f["topic"],
                "finding": f["finding"],
                "importance": f["importance"],
                "timestamp": f["timestamp"],
            }
            for f in top_findings
        ],
        "recent_recommendations": [
            {
                "asset": r["asset"],
                "direction": r["direction"],
                "confidence": r["confidence"],
                "status": r["status"],
                "timestamp": r["timestamp"],
            }
            for r in recent_recs
        ],
    }
    print(json.dumps(result, indent=2, default=str))


# ============================================================================
# COMMAND: steer
# ============================================================================


def cmd_steer(args: argparse.Namespace) -> None:
    """Send steering input to the running agent."""
    message = " ".join(args.message) if args.message else ""

    if not message:
        print()
        print(f"  {_yellow('No steering message provided.')}")
        print(f"  Usage: {_cyan('aeonctl steer \"Focus on AI semiconductor stocks\"')}")
        print()
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Write directly to consciousness SQLite
    db_path = CONSCIOUSNESS_DB
    if not db_path.exists():
        print()
        print(f"  {_yellow('Consciousness database not found.')}")
        print(f"  Start the agent first: {_cyan('aeonctl start')}")
        print()
        return

    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        ts = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO steering_inputs (timestamp, input_text, source) VALUES (?, ?, ?)",
            (ts, message, "cli"),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        print(f"  {_red('Error writing steering input:')} {exc}")
        return

    print()
    print(f"  {_green('Steering input sent.')} The agent will pick it up in the next cycle.")
    print(f"  Message: {_bold(message[:100])}")
    print()


# ============================================================================
# COMMAND: log
# ============================================================================


def cmd_log(args: argparse.Namespace) -> None:
    """Show the consciousness stream (what the agent is thinking)."""
    log_path = STREAM_LOG
    n = args.lines

    if args.follow:
        _follow_log(log_path)
        return

    if not log_path.exists():
        print()
        print(f"  {_dim('No consciousness stream log found.')}")
        print(f"  Start the agent first: {_cyan('aeonctl start')}")
        print()
        return

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError as exc:
        print(f"  {_red('Error reading log:')} {exc}")
        return

    if not lines:
        print(f"  {_dim('Consciousness stream is empty.')}")
        return

    print()
    print(f"  {_bold('Consciousness Stream')} (last {n} entries)")
    print(_cyan("  " + "-" * 60))

    for line in lines[-n:]:
        _print_stream_line(line.rstrip("\n"))

    print()


def _follow_log(log_path: Path) -> None:
    """Tail -f style following of the consciousness log."""
    print()
    print(f"  {_bold('Consciousness Stream')} (live, Ctrl+C to exit)")
    print(_cyan("  " + "-" * 60))

    if not log_path.exists():
        print(f"  {_dim('Waiting for consciousness stream to start...')}")

    try:
        # Print existing content first
        if log_path.exists():
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                for line in lines[-20:]:
                    _print_stream_line(line.rstrip("\n"))

        # Then follow new entries
        last_size = log_path.stat().st_size if log_path.exists() else 0
        while True:
            if not log_path.exists():
                time.sleep(1)
                continue

            current_size = log_path.stat().st_size
            if current_size > last_size:
                with open(log_path, "r", encoding="utf-8") as f:
                    f.seek(last_size)
                    new_lines = f.readlines()
                    for line in new_lines:
                        _print_stream_line(line.rstrip("\n"))
                last_size = current_size
            time.sleep(0.5)

    except KeyboardInterrupt:
        print()
        print(f"  {_dim('Stream following stopped.')}")
        print()


def _print_stream_line(line: str) -> None:
    """Print a single consciousness stream line with colour coding."""
    if not line.strip():
        return

    # Parse category from [timestamp] [CATEGORY] message
    category = ""
    if "] [" in line:
        try:
            parts = line.split("] [", 1)
            cat_end = parts[1].index("]")
            category = parts[1][:cat_end]
        except (IndexError, ValueError):
            pass

    if category == "THINKING":
        print(f"  {_cyan(line)}")
    elif category == "PLANNING":
        print(f"  {_c(line, _BLUE)}")
    elif category == "FINDING":
        print(f"  {_green(line)}")
    elif category == "RECOMMENDATION":
        print(f"  {_bright_yellow(line)}")
    elif category == "ERROR":
        print(f"  {_red(line)}")
    elif category == "STEERING":
        print(f"  {_magenta(line)}")
    elif category == "SLEEPING":
        print(f"  {_dim(line)}")
    elif category == "TOOL_CALL":
        print(f"  {_dim(line)}")
    elif category == "SYSTEM":
        print(f"  {_yellow(line)}")
    else:
        print(f"  {line}")


# ============================================================================
# COMMAND: history
# ============================================================================


def cmd_history(args: argparse.Namespace) -> None:
    """Show recent recommendations and findings."""
    if not _db_available():
        _print_not_initialized()
        return

    conn = _open_ro(CONSCIOUSNESS_DB)
    if conn is None:
        _print_not_initialized()
        return

    try:
        limit = 50 if args.full else 15

        if args.json:
            _print_history_json(conn, limit, args)
            return

        print()

        # Recommendations
        if not args.findings_only:
            recs = conn.execute(
                f"SELECT id, timestamp, asset, direction, thesis, confidence, "
                f"evidence, status, outcome, actual_return "
                f"FROM recommendations ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()

            if recs:
                print(f"  {_bold('Recent Recommendations')}")
                print(f"  {_dim('-' * 60)}")
                for r in recs:
                    ts = r["timestamp"][:16]
                    asset = r["asset"] or "?"
                    direction = (r["direction"] or "?").upper()
                    confidence = r["confidence"] or 0.0
                    status = r["status"] or "sent"
                    thesis = r["thesis"] or ""

                    if direction in ("BUY", "LONG"):
                        dir_str = _green(direction)
                    elif direction in ("SELL", "SHORT"):
                        dir_str = _red(direction)
                    else:
                        dir_str = _yellow(direction)

                    print(f"  {_dim(ts)}  {_bold(asset):>10} {dir_str:<8} "
                          f"conf: {confidence:.0%}  [{status}]")
                    if thesis:
                        print(f"    {_dim(thesis[:80])}")
                print()
            else:
                print(f"  {_dim('No recommendations yet.')}")
                print()

        # Findings
        if not args.recs_only:
            findings = conn.execute(
                f"SELECT id, timestamp, topic, finding, source, importance "
                f"FROM findings ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()

            if findings:
                print(f"  {_bold('Recent Research Findings')}")
                print(f"  {_dim('-' * 60)}")
                for f in findings:
                    ts = f["timestamp"][:16]
                    topic = f["topic"][:20]
                    finding = f["finding"][:70]
                    importance = f["importance"]
                    source = f["source"]

                    if importance >= 0.8:
                        imp_str = _red(f"[{importance:.1f}]")
                    elif importance >= 0.5:
                        imp_str = _yellow(f"[{importance:.1f}]")
                    else:
                        imp_str = _dim(f"[{importance:.1f}]")

                    print(f"  {_dim(ts)}  {imp_str} [{_cyan(topic)}] {finding}")
                    if source:
                        print(f"    {_dim(f'source: {source}')}")
                print()
            else:
                print(f"  {_dim('No research findings yet.')}")
                print()

        # Steering history
        if args.full:
            steering = conn.execute(
                "SELECT timestamp, input_text, source FROM steering_inputs "
                "ORDER BY timestamp DESC LIMIT 10"
            ).fetchall()
            if steering:
                print(f"  {_bold('Steering History')}")
                print(f"  {_dim('-' * 60)}")
                for s in steering:
                    ts = s["timestamp"][:16]
                    text = s["input_text"][:60]
                    src = s["source"]
                    print(f"  {_dim(ts)}  [{src}] {_magenta(text)}")
                print()

    finally:
        conn.close()


def _print_history_json(conn: sqlite3.Connection, limit: int, args: argparse.Namespace) -> None:
    result: dict[str, Any] = {}

    if not args.findings_only:
        recs = conn.execute(
            "SELECT * FROM recommendations ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        result["recommendations"] = [
            {**dict(r), "evidence": _safe_json(r["evidence"]), "metadata": _safe_json(r["metadata"])}
            for r in recs
        ]

    if not args.recs_only:
        findings = conn.execute(
            "SELECT * FROM findings ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        result["findings"] = [dict(f) for f in findings]

    print(json.dumps(result, indent=2, default=str))


# ============================================================================
# COMMAND: config
# ============================================================================


def cmd_config(args: argparse.Namespace) -> None:
    """Show current configuration."""
    # Try to load config via the standard path
    try:
        from aeon.core.config import HedgeFundConfig
        cfg = HedgeFundConfig.from_env()
    except Exception as exc:
        print(f"  {_red('Error loading config:')} {exc}")
        return

    if args.json:
        import dataclasses
        d = dataclasses.asdict(cfg)
        # Mask sensitive values
        for key in d:
            if "password" in key or "secret" in key or "key" in key.lower():
                if d[key]:
                    d[key] = d[key][:3] + "..." + d[key][-2:] if len(d[key]) > 5 else "****"
        print(json.dumps(d, indent=2, default=str))
        return

    print()
    print(f"  {_bold('AEON Configuration')}")
    print(_cyan("  " + "=" * 50))

    print(f"\n  {_cyan('LLM Provider')}")
    print(f"    Provider:       {_bold(cfg.llm_provider)}")
    print(f"    Model:          {cfg.llm_model}")
    if cfg.llm_provider == "ollama":
        print(f"    Ollama Host:    {cfg.ollama_host}")
    elif cfg.llm_provider == "bedrock":
        print(f"    Region:         {cfg.bedrock_aws_region}")
        print(f"    Model ID:       {cfg.bedrock_model_id}")

    print(f"\n  {_cyan('Research')}")
    print(f"    Daily Budget:   ${cfg.research_budget_daily_usd:.2f}")
    print(f"    Market Focus:   {', '.join(cfg.market_focus)}")
    print(f"    Update Freq:    every {cfg.update_frequency_minutes} minutes")
    print(f"    Max Depth:      {cfg.max_research_depth} tool calls/chain")
    print(f"    Search:         {cfg.search_provider}")

    print(f"\n  {_cyan('User')}")
    print(f"    Email:          {cfg.user_email or _dim('not set')}")
    print(f"    Name:           {cfg.user_name or _dim('not set')}")
    guidance = cfg.guidance_prompt[:60] + "..." if len(cfg.guidance_prompt) > 60 else cfg.guidance_prompt
    print(f"    Guidance:       {guidance or _dim('not set')}")

    print(f"\n  {_cyan('Email')}")
    print(f"    SMTP Host:      {cfg.smtp_host or _dim('not configured')}")
    print(f"    Sender:         {cfg.email_sender or _dim('not set')}")
    print(f"    Recipient:      {cfg.email_recipient or _dim('not set')}")
    print(f"    IMAP Host:      {cfg.imap_host or _dim('not configured')}")

    print(f"\n  {_cyan('Paths')}")
    print(f"    Data Dir:       {cfg.data_dir}")
    print(f"    Consciousness:  {cfg.data_dir}/consciousness.db")
    print(f"    Stream Log:     {cfg.data_dir}/consciousness.log")

    print()


# ============================================================================
# COMMAND: start
# ============================================================================


def cmd_start(args: argparse.Namespace) -> None:
    """Start the AEON research agent."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if args.daemon:
        _start_daemon()
    else:
        _start_foreground()


def _start_daemon() -> None:
    """Start the agent as a background daemon."""
    if _is_daemon_running():
        pid = _get_pid()
        print(f"  {_yellow('AEON is already running')} (PID: {pid}).")
        print(f"  Use '{_cyan('aeonctl stop')}' to stop it first.")
        return

    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.exists() else sys.executable

    try:
        with open(LOG_FILE, "a") as log_fh:
            process = subprocess.Popen(
                [python_exe, "-m", "aeon"],
                cwd=str(PROJECT_ROOT),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except FileNotFoundError:
        print(f"  {_red('Error:')} Could not find Python at '{python_exe}'.")
        sys.exit(1)

    PID_FILE.write_text(str(process.pid))
    print()
    print(f"  {_green('AEON started successfully.')}")
    print(f"  PID:     {_bold(str(process.pid))}")
    print(f"  Log:     {LOG_FILE}")
    print()
    print(f"  Monitor: {_cyan('aeonctl status')}")
    print(f"  Stream:  {_cyan('aeonctl log -f')}")
    print(f"  Steer:   {_cyan('aeonctl steer \"Focus on AI stocks\"')}")
    print(f"  Stop:    {_cyan('aeonctl stop')}")
    print()


def _start_foreground() -> None:
    """Start the agent with the interactive TUI."""
    from aeon.tui.app import run_tui
    run_tui()


# ============================================================================
# COMMAND: stop
# ============================================================================


def cmd_stop(args: argparse.Namespace) -> None:
    """Stop the running AEON agent."""
    if not PID_FILE.exists():
        print(f"  {_yellow('AEON is not running')} (no PID file).")
        return

    pid = _get_pid()
    if pid is None:
        PID_FILE.unlink(missing_ok=True)
        print(f"  {_yellow('AEON is not running')} (empty PID file).")
        return

    # Check if process exists
    try:
        os.kill(pid, 0)
    except OSError:
        PID_FILE.unlink(missing_ok=True)
        print(f"  {_yellow('AEON was not running')} (stale PID file removed).")
        return

    print(f"  Sending SIGTERM to AEON (PID: {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as e:
        print(f"  {_red('Error:')} Could not signal process: {e}")
        sys.exit(1)

    # Wait for graceful shutdown
    waited = 0.0
    while waited < 10:
        try:
            os.kill(pid, 0)
            time.sleep(0.5)
            waited += 0.5
        except OSError:
            break

    # Force kill if still running
    try:
        os.kill(pid, 0)
        print(f"  {_yellow('Graceful shutdown timed out')} -- sending SIGKILL...")
        os.kill(pid, signal.SIGKILL)
        time.sleep(1)
    except OSError:
        pass

    PID_FILE.unlink(missing_ok=True)
    print(f"  {_green('AEON stopped.')}")


# ============================================================================
# Daemon management helpers
# ============================================================================


def _is_daemon_running() -> bool:
    """Check if the daemon is running."""
    pid = _get_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        PID_FILE.unlink(missing_ok=True)
        return False


def _get_pid() -> int | None:
    """Read the PID from the PID file."""
    if not PID_FILE.exists():
        return None
    try:
        text = PID_FILE.read_text().strip()
        return int(text) if text else None
    except (ValueError, OSError):
        return None


# ============================================================================
# Argument parser
# ============================================================================


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aeonctl",
        description="AEON AI Hedge Fund Manager -- CLI Control",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              aeonctl                          Launch interactive TUI (default)
              aeonctl start                    Start in interactive mode (foreground TUI)
              aeonctl start -d                 Start as background daemon
              aeonctl status                   Show research status
              aeonctl status --json            Machine-readable status
              aeonctl steer "Focus on NVDA"    Send steering input
              aeonctl log -f                   Follow consciousness stream (live)
              aeonctl log -n 100               Show last 100 stream entries
              aeonctl history                  Show recent recommendations/findings
              aeonctl history --full           Show full history
              aeonctl config                   Show current configuration
              aeonctl stop                     Stop the running agent
        """),
    )

    sub = parser.add_subparsers(dest="command", title="commands")

    # start
    start_p = sub.add_parser("start", help="Start the research agent")
    start_p.add_argument("-d", "--daemon", action="store_true",
                         help="Run as background daemon")
    start_p.set_defaults(func=cmd_start)

    # status
    status_p = sub.add_parser("status", help="Show current research status")
    status_p.add_argument("--json", action="store_true",
                          help="Machine-readable JSON output")
    status_p.set_defaults(func=cmd_status)

    # steer
    steer_p = sub.add_parser("steer",
                             help="Send steering input to the agent")
    steer_p.add_argument("message", nargs="*",
                         help="Steering message (e.g., 'Focus on AI stocks')")
    steer_p.set_defaults(func=cmd_steer)

    # log
    log_p = sub.add_parser("log",
                           help="Show consciousness stream (agent's thinking)")
    log_p.add_argument("-f", "--follow", action="store_true",
                       help="Follow the stream in real time (like tail -f)")
    log_p.add_argument("-n", "--lines", type=int, default=50,
                       help="Number of lines to show (default: 50)")
    log_p.set_defaults(func=cmd_log)

    # history
    hist_p = sub.add_parser("history",
                            help="Show recent recommendations and findings")
    hist_p.add_argument("--full", action="store_true",
                        help="Show all entries (not just recent)")
    hist_p.add_argument("--recs-only", action="store_true",
                        help="Show only recommendations")
    hist_p.add_argument("--findings-only", action="store_true",
                        help="Show only findings")
    hist_p.add_argument("--json", action="store_true",
                        help="Machine-readable JSON output")
    hist_p.set_defaults(func=cmd_history)

    # config
    config_p = sub.add_parser("config",
                              help="Show current configuration")
    config_p.add_argument("--json", action="store_true",
                          help="Machine-readable JSON output")
    config_p.set_defaults(func=cmd_config)

    # stop
    stop_p = sub.add_parser("stop", help="Stop the running agent")
    stop_p.set_defaults(func=cmd_stop)

    return parser


# ============================================================================
# Main
# ============================================================================


def _ensure_project_dir() -> None:
    """Ensure we're in the project directory for .env and data/ access."""
    # If we can find AEON_HOME, cd there
    aeon_home = os.environ.get("AEON_HOME")
    if aeon_home and Path(aeon_home).is_dir():
        os.chdir(aeon_home)
        return
    # If aeon/app.py exists relative to this file's parent, we're in the project
    project_root = Path(__file__).resolve().parent.parent
    if (project_root / "aeon" / "app.py").exists():
        os.chdir(project_root)


def main() -> None:
    _ensure_project_dir()

    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        # Default: launch interactive TUI
        _start_foreground()
    elif hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
