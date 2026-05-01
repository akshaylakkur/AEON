"""Neural Orchestrator - Task-driven research brain for the AEON Hedge Fund Manager.

Operates in a deliberate plan-execute-analyze loop:

1. PLAN   — LLM decomposes the user's guidance into concrete subtasks
2. RESEARCH — For each subtask, make one tool call at a time, analyze results
3. COMPILE — Synthesize all findings and email a report to the user
4. PLAN NEXT — LLM plans the follow-up session based on what it learned
5. SLEEP  — Strategic pause to manage costs

All reasoning is LLM-driven.  The orchestrator controls the cadence:
one tool call per LLM turn, with logging and memory between each.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from aeon.core.constants import (
    MAX_RAPID_CYCLES,
    MAX_SUBTASKS_PER_SESSION,
    MAX_TOOL_CALLS_PER_SUBTASK,
    MARKET_HOURS,
    SLEEP_BASE,
    SLEEP_BETWEEN_SESSIONS,
    SLEEP_BETWEEN_SUBTASKS,
    SLEEP_COST_EXCEEDED,
    SLEEP_MARKET_CLOSED,
)
from aeon.core.context_compactor import ContextCompactor, build_session_summary
from aeon.core.event_bus import EventBus, Priority
from aeon.core.events import InternalThought
from aeon.core.reasoning_log import ReasoningLog, get_reasoning_log
from aeon.core.state_machine import State, StateMachine

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# Data structures
# ------------------------------------------------------------------ #


@dataclass
class Subtask:
    """A single research subtask planned by the LLM."""

    id: int
    description: str
    objective: str
    status: str = "pending"  # pending, in_progress, completed, skipped
    findings: list[str] = field(default_factory=list)
    tool_calls_made: int = 0
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str | None = None


@dataclass
class ResearchSession:
    """A complete research session with subtasks."""

    session_id: int
    guidance: str
    subtasks: list[Subtask] = field(default_factory=list)
    status: str = "planning"
    findings_summary: str = ""
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str | None = None
    next_session_plan: str = ""
    db_row_id: int | None = None


@dataclass
class ResearchContext:
    """Snapshot of agent state used when building prompts."""

    current_time: str
    market_hours_status: str
    daily_budget_remaining: float
    daily_cost_so_far: float
    user_guidance: str
    latest_steering: str | None
    recent_findings: list[dict[str, Any]]
    recent_recommendations: list[dict[str, Any]]
    research_summary: dict[str, Any]
    available_tools: list[dict[str, Any]]
    cycle_number: int
    consciousness_summary: str
    last_session_plan: str | None = None


# ------------------------------------------------------------------ #
# Neural Orchestrator
# ------------------------------------------------------------------ #


class NeuralOrchestrator:
    """Task-driven research brain.

    Runs a continuous loop of:
      Plan subtasks → Execute one-at-a-time → Compile report → Sleep
    """

    def __init__(
        self,
        *,
        llm_client: Any,
        tool_registry: Any,
        consciousness: Any,
        consciousness_stream: Any | None = None,
        state_machine: StateMachine,
        event_bus: EventBus,
        config: Any,
        reasoning_log: ReasoningLog | None = None,
    ) -> None:
        self._llm = llm_client
        self._tools = tool_registry
        self._consciousness = consciousness
        self._stream = consciousness_stream
        self._state_machine = state_machine
        self._event_bus = event_bus
        self._config = config
        self._reasoning = reasoning_log or get_reasoning_log()

        self._running = False
        self._session_count = 0
        self._shutdown_event = asyncio.Event()
        self._steering_event = asyncio.Event()
        self._steering_received = False
        self._task: asyncio.Task[Any] | None = None

        # Context compactor — prevents unbounded context growth
        self._compactor = ContextCompactor(
            llm_client=llm_client,
            consciousness=consciousness,
            config=config,
            consciousness_stream=consciousness_stream,
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def run(self) -> None:
        """Main entry point.  Runs the research brain indefinitely."""
        self._running = True
        self._log_stream("SYSTEM", "AEON research brain starting up")

        while self._running:
            try:
                self._session_count += 1
                session_start = time.monotonic()

                session = await self._run_session_until_findings()
                if not self._running or session is None:
                    break

                # Phase 3: Compile findings and email report
                await self._compile_and_communicate(session)

                # Phase 4: Plan the next session
                session.next_session_plan = await self._plan_next_session(
                    session
                )
                session.status = "completed"
                session.completed_at = datetime.now(timezone.utc).isoformat()
                self._persist_session(session)

                elapsed = time.monotonic() - session_start
                self._log_stream(
                    "SYSTEM",
                    f"Session #{self._session_count} complete in {elapsed:.0f}s "
                    f"({len(session.subtasks)} subtasks)",
                )

                # Record session in context compactor
                total_tool_calls = sum(
                    st.tool_calls_made for st in session.subtasks
                )
                report_sent = bool(session.findings_summary)
                session_summary_text = build_session_summary(
                    session_id=session.session_id,
                    timestamp=session.completed_at or datetime.now(timezone.utc).isoformat(),
                    guidance=session.guidance,
                    subtasks=session.subtasks,
                    total_tool_calls=total_tool_calls,
                    report_sent=report_sent,
                    report_subject=(
                        f"Session #{session.session_id} report"
                        if report_sent
                        else ""
                    ),
                    next_plan=session.next_session_plan,
                )
                self._compactor.record_session(session_summary_text)

                # Check if context compaction is needed
                if self._compactor.needs_compaction:
                    await self._compactor.compact()

                # Phase 5: Strategic sleep
                await self._strategic_sleep(session)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log_stream("ERROR", f"Session error: {exc}")
                logger.exception("Research session failed")
                await asyncio.sleep(60)

        self._log_stream("SYSTEM", "Research brain loop exited")

    # Maximum retry attempts when a session produces no findings
    _MAX_EMPTY_RETRIES = 3

    async def _run_session_until_findings(self) -> ResearchSession | None:
        """Plan and execute a session, retrying if no findings are produced.

        If a session completes with zero actionable findings across all
        subtasks, the agent replans with an explicit instruction to try
        different tools/queries rather than giving up and sleeping.
        Returns the session once it has findings, or ``None`` if the agent
        was stopped or steering interrupted.
        """
        failed_approaches: list[str] = []

        for attempt in range(1, self._MAX_EMPTY_RETRIES + 1):
            if not self._running:
                return None

            # If steering arrived between attempts, reset the flag so the
            # new plan picks it up (don't skip straight to sleep).
            if self._steering_received and attempt > 1:
                self._steering_received = False

            # Phase 1: Plan subtasks (with retry context if previous attempt failed)
            session = await self._plan_session(failed_approaches=failed_approaches)
            if not self._running:
                return None

            # Phase 2: Execute subtasks one at a time
            for subtask in session.subtasks:
                if not self._running:
                    return None
                if self._steering_received:
                    self._steering_received = False
                    self._log_stream(
                        "STEERING", "New steering received — replanning"
                    )
                    break
                await self._execute_subtask(session, subtask)
                await asyncio.sleep(SLEEP_BETWEEN_SUBTASKS)

            if not self._running:
                return None

            # Check if we got any actionable findings
            total_findings = sum(len(st.findings) for st in session.subtasks)
            total_tool_calls = sum(st.tool_calls_made for st in session.subtasks)

            if total_findings > 0:
                return session

            # No findings — record what was tried and retry
            tried = "; ".join(
                st.description for st in session.subtasks
            )
            failed_approaches.append(
                f"Attempt {attempt}: tried [{tried}] with "
                f"{total_tool_calls} tool calls — no actionable findings"
            )

            if attempt < self._MAX_EMPTY_RETRIES:
                self._log_stream(
                    "SYSTEM",
                    f"Session produced no actionable findings "
                    f"({total_tool_calls} tool calls across "
                    f"{len(session.subtasks)} subtasks). "
                    f"Retrying with different approach "
                    f"(attempt {attempt + 1}/{self._MAX_EMPTY_RETRIES})...",
                )
                # Brief pause before replanning
                await asyncio.sleep(SLEEP_BETWEEN_SUBTASKS * 2)
            else:
                self._log_stream(
                    "SYSTEM",
                    f"No findings after {self._MAX_EMPTY_RETRIES} attempts. "
                    f"Will try a fresh approach next session.",
                )
                return session

        return session  # unreachable, but satisfies type checker

    async def shutdown(self) -> None:
        """Gracefully stop the research brain."""
        if not self._running:
            return
        self._running = False
        self._shutdown_event.set()
        self._log_stream("SYSTEM", "Research brain shutting down")
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    stop = shutdown

    async def inject_steering(self, steering_text: str) -> None:
        """Inject user steering to influence the next research cycle.

        If the agent is sleeping, this wakes it immediately so the new
        guidance is acted on without waiting for the sleep timer.
        """
        if hasattr(self._consciousness, "store_steering_input"):
            self._consciousness.store_steering_input(
                steering_text, datetime.now(timezone.utc)
            )
        self._steering_received = True
        self._steering_event.set()
        self._log_stream(
            "STEERING", f"User input received: {steering_text[:200]}"
        )

    # ------------------------------------------------------------------ #
    # Phase 1: Planning
    # ------------------------------------------------------------------ #

    async def _plan_session(
        self, failed_approaches: list[str] | None = None,
    ) -> ResearchSession:
        """Ask the LLM to decompose the guidance into subtasks."""
        await self._state_machine.transition_to(State.PLANNING)
        context = await self._build_context()

        self._log_stream(
            "PLANNING",
            f"Session #{self._session_count}: Planning research subtasks...",
        )

        system_prompt = self._build_planning_prompt(context)
        user_msg = self._build_planning_user_message(
            context, failed_approaches=failed_approaches,
        )

        response, cost = await self._llm.chat(
            system_prompt=system_prompt,
            messages=[{"role": "user", "content": user_msg}],
            tools=None,
            use_cache=False,
        )

        # Stream the LLM's raw planning reasoning
        if response.thinking.strip():
            self._log_stream("THINKING", response.thinking.strip())

        # Try parsing from thinking first, then from content
        subtasks = self._parse_subtasks(response.thinking)
        if len(subtasks) == 1 and subtasks[0].description == "General research":
            # Fallback failed on thinking — try content field if available
            content = getattr(response, "content", "") or ""
            if content.strip():
                alt = self._parse_subtasks(content)
                if len(alt) > 1 or (
                    len(alt) == 1 and alt[0].description != "General research"
                ):
                    subtasks = alt

        session = ResearchSession(
            session_id=self._session_count,
            guidance=context.user_guidance or "General market research",
        )
        session.subtasks = subtasks

        for i, st in enumerate(subtasks, 1):
            self._log_stream("PLANNING", f"  Subtask {i}: {st.description}")

        if hasattr(self._consciousness, "store_thought"):
            self._consciousness.store_thought(
                f"Session #{self._session_count} plan: "
                + "; ".join(st.description for st in subtasks),
                importance=0.7,
            )

        # Persist the session plan
        row_id = self._persist_session(session)
        session.db_row_id = row_id

        return session

    def _build_planning_prompt(self, ctx: ResearchContext) -> str:
        enrichment = self._llm.get_context_enrichment()
        return (
            "You are AEON, an AI hedge fund research manager.\n\n"
            f"{enrichment}\n\n"
            f"Daily budget: ${ctx.daily_cost_so_far:.4f} spent of "
            f"${ctx.daily_cost_so_far + ctx.daily_budget_remaining:.2f}\n\n"
            "Your job is to plan the next research session.  Return 2-4 focused, "
            "specific subtasks.  Each MUST target a concrete research question — "
            "NOT generic exploration.\n\n"
            "## Data Source Constraints\n"
            "- **search_news / search_web**: Best for current events. DuckDuckGo "
            "free tier has rate limits — use focused queries, not broad ones.\n"
            "- **get_market_data / get_price_history**: Good for specific assets. "
            "Yahoo Finance may return 429 errors — only query assets you are "
            "actively analyzing.\n"
            "- **Memory tools (recall_findings, recall_memories, etc.)**: ONLY useful "
            "if previous sessions have stored data.  On a fresh database these return "
            "nothing.  Do NOT plan subtasks that rely on recall if this is an early session.\n"
            "- Each subtask gets a MAXIMUM of 8 tool calls.  Plan accordingly.\n\n"
            "## Good vs Bad Subtasks\n"
            "GOOD: {\"description\": \"NVIDIA earnings impact on AI chip sector\", "
            "\"objective\": \"Search for NVIDIA's latest earnings results and analyst "
            "reactions, then get NVDA price data to assess market response\"}\n"
            "GOOD: {\"description\": \"Bitcoin ETF flow analysis\", "
            "\"objective\": \"Find recent Bitcoin ETF inflow/outflow data and correlate "
            "with BTC price movement over the past week\"}\n"
            "BAD: {\"description\": \"General market research\", "
            "\"objective\": \"Look at the market and see what's happening\"}\n"
            "BAD: {\"description\": \"Recall previous findings\", "
            "\"objective\": \"Check memory for past research\"}\n\n"
            "## Available Tools\n"
            f"{self._tools.get_tool_summary() if hasattr(self._tools, 'get_tool_summary') else 'market data, web search, news search, scraping, memory tools'}\n\n"
            "## Output Format\n"
            "Return a JSON array of subtasks:\n"
            '```json\n[\n  {"description": "short title", "objective": "what to accomplish and why"},\n  ...\n]\n```\n'
            "Keep subtasks focused and achievable with 3-5 tool calls each.  "
            "Order them logically: gather data first, then analyze.\n"
        )

    def _build_planning_user_message(
        self,
        ctx: ResearchContext,
        failed_approaches: list[str] | None = None,
    ) -> str:
        parts: list[str] = []

        # Include compacted context from prior sessions if available
        compacted_prefix = self._compactor.get_context_prefix()
        if compacted_prefix:
            parts.append(compacted_prefix)

        # If this is a retry after empty results, tell the LLM what failed
        if failed_approaches:
            parts.append(
                "## IMPORTANT — Previous Attempts Found Nothing\n"
                "The following approaches were already tried and returned "
                "NO actionable findings. You MUST try completely different "
                "tools, queries, or angles this time.\n"
                + "\n".join(f"- {a}" for a in failed_approaches)
                + "\n\nDo NOT repeat these approaches. Try different search "
                "terms, different data sources, or different assets."
            )

        parts.append(
            f"## User's Investment Focus\n{ctx.user_guidance or 'No specific guidance. Research broadly.'}"
        )

        if ctx.latest_steering:
            parts.append(
                f"\n## Latest Steering Input\n{ctx.latest_steering}\n"
                "Prioritize this in your research plan."
            )

        if ctx.last_session_plan:
            parts.append(
                f"\n## Follow-up from Previous Session\n{ctx.last_session_plan}"
            )

        if ctx.recent_findings:
            parts.append("\n## Recent Findings (already known)")
            for f in ctx.recent_findings[:8]:
                topic = f.get("topic", "?") if isinstance(f, dict) else "?"
                finding = f.get("finding", "") if isinstance(f, dict) else str(f)
                parts.append(f"- [{topic}] {finding[:150]}")
            parts.append(
                "\nBuild on these — don't repeat research you've already done."
            )

        if ctx.daily_budget_remaining < 0.20:
            parts.append(
                "\nWARNING: Budget is low.  Plan only 2-3 essential subtasks."
            )

        parts.append(
            "\nCreate your research plan now.  Return a JSON array of subtasks."
        )
        return "\n".join(parts)

    def _parse_subtasks(self, text: str) -> list[Subtask]:
        """Extract subtask list from LLM planning response."""
        parsed = _try_parse_json(text)
        subtasks: list[Subtask] = []

        if isinstance(parsed, list):
            for i, item in enumerate(parsed[:MAX_SUBTASKS_PER_SESSION]):
                if isinstance(item, dict):
                    subtasks.append(
                        Subtask(
                            id=i + 1,
                            description=item.get("description", f"Subtask {i+1}"),
                            objective=item.get("objective", item.get("description", "")),
                        )
                    )
        elif isinstance(parsed, dict) and "subtasks" in parsed:
            return self._parse_subtasks(json.dumps(parsed["subtasks"]))

        if not subtasks:
            # Fallback: treat entire response as a single subtask
            subtasks.append(
                Subtask(
                    id=1,
                    description="General research",
                    objective=text[:500],
                )
            )

        return subtasks

    # ------------------------------------------------------------------ #
    # Phase 2: Subtask Execution
    # ------------------------------------------------------------------ #

    async def _execute_subtask(
        self, session: ResearchSession, subtask: Subtask
    ) -> None:
        """Execute a single subtask with one-tool-at-a-time loop.

        The LLM controls tool invocation. Each turn:
        1. LLM thinks and optionally requests a tool call
        2. We stream its raw thinking to the consciousness log
        3. If a tool was requested, we execute it and feed results back
        4. The LLM decides what to do next based on the result
        """
        await self._state_machine.transition_to(State.RESEARCHING)
        subtask.status = "in_progress"

        self._log_stream(
            "RESEARCH",
            f"Starting subtask {subtask.id}: {subtask.description}",
        )

        context = await self._build_context()
        system_prompt = self._build_subtask_prompt(context, subtask, session)

        conversation: list[dict[str, Any]] = [
            {"role": "user", "content": subtask.objective},
        ]

        last_thinking = ""

        while subtask.tool_calls_made < MAX_TOOL_CALLS_PER_SUBTASK:
            if not self._running or self._steering_received:
                break

            if self._llm.is_budget_exceeded():
                self._log_stream(
                    "SYSTEM", "Budget exceeded — stopping subtask"
                )
                break

            try:
                (
                    response,
                    cost,
                    results,
                    conversation,
                    done,
                ) = await self._llm.chat_with_tools_single_turn(
                    system_prompt=system_prompt,
                    conversation=conversation,
                )
            except Exception as exc:
                self._log_stream(
                    "ERROR", f"LLM call failed: {exc}"
                )
                break

            # Stream the model's raw thinking — this is the core of the
            # consciousness log. Whatever the model is reasoning about
            # goes directly to the stream.
            thinking = getattr(response, "thinking", "") or ""
            if thinking.strip():
                self._log_stream("THINKING", thinking.strip())
                last_thinking = thinking.strip()

            if done:
                if thinking.strip():
                    subtask.findings.append(thinking[:2000])
                break

            # The LLM requested tool calls — log which ones and capture
            # intermediate findings from successful results
            for result in results:
                tool_name = (
                    result.get("tool_name", "unknown")
                    if isinstance(result, dict)
                    else "unknown"
                )
                subtask.tool_calls_made += 1
                self._log_stream(
                    "TOOL_CALL",
                    f"[{subtask.description}] {tool_name} "
                    f"(call {subtask.tool_calls_made}/{MAX_TOOL_CALLS_PER_SUBTASK}) → "
                    + _summarize_tool_result(result),
                )

                # Capture intermediate findings from successful tool calls
                if isinstance(result, dict) and result.get("error") is None:
                    tool_data = result.get("result")
                    if tool_data:
                        finding_snippet = _extract_intermediate_finding(
                            tool_name, tool_data
                        )
                        if finding_snippet:
                            subtask.findings.append(finding_snippet)

                if hasattr(self._consciousness, "store_tool_result"):
                    try:
                        self._consciousness.store_tool_result(
                            tool_name=tool_name,
                            result=result.get("result") or result.get("error")
                            if isinstance(result, dict)
                            else result,
                            success=not (
                                isinstance(result, dict)
                                and result.get("error") is not None
                            ),
                            cycle_id=self._session_count,
                        )
                    except Exception:
                        pass

            await asyncio.sleep(1)

        # If we exhausted tool calls without a done=True final response,
        # capture the last thinking as a finding if it has substance
        if (
            subtask.tool_calls_made >= MAX_TOOL_CALLS_PER_SUBTASK
            and last_thinking
            and not any(last_thinking[:200] in f for f in subtask.findings)
        ):
            subtask.findings.append(
                f"[Partial analysis after {subtask.tool_calls_made} tool calls] "
                + last_thinking[:2000]
            )

        await self._state_machine.transition_to(State.ANALYZING)
        subtask.status = "completed"
        subtask.completed_at = datetime.now(timezone.utc).isoformat()

        for finding_text in subtask.findings:
            if hasattr(self._consciousness, "store_finding"):
                try:
                    self._consciousness.store_finding(
                        topic=subtask.description,
                        finding=finding_text[:1000],
                        source=f"session_{session.session_id}_subtask_{subtask.id}",
                        importance=0.6,
                    )
                except Exception:
                    pass

        self._log_stream(
            "FINDING",
            f"Subtask {subtask.id} complete: {subtask.description} "
            f"({subtask.tool_calls_made} tool calls, "
            f"{len(subtask.findings)} findings)",
        )

    def _build_subtask_prompt(
        self,
        ctx: ResearchContext,
        subtask: Subtask,
        session: ResearchSession,
    ) -> str:
        enrichment = self._llm.get_context_enrichment()

        prior = ""
        completed = [
            st for st in session.subtasks if st.status == "completed"
        ]
        if completed:
            prior_parts = []
            for st in completed:
                findings_text = "; ".join(
                    f[:200] for f in st.findings
                ) or "no findings"
                prior_parts.append(f"- {st.description}: {findings_text}")
            prior = (
                "\n## Findings from Earlier Subtasks\n"
                + "\n".join(prior_parts)
                + "\nBuild on these findings.  Don't repeat work.\n"
            )

        tool_summary = ""
        if hasattr(self._tools, "get_tool_summary"):
            tool_summary = self._tools.get_tool_summary()

        compacted_prefix = self._compactor.get_context_prefix()
        compacted_section = (
            f"\n{compacted_prefix}\n" if compacted_prefix else ""
        )

        return (
            "You are AEON, an AI hedge fund research manager.\n\n"
            f"{enrichment}\n\n"
            f"{compacted_section}"
            f"## Current Subtask\n"
            f"**{subtask.description}**\n"
            f"Objective: {subtask.objective}\n\n"
            f"## User's Investment Focus\n"
            f"{ctx.user_guidance or 'General market research'}\n"
            f"{prior}\n"
            f"## Available Tools\n{tool_summary}\n\n"
            "## How to Work\n"
            "Think step by step. For each step:\n"
            "1. Reason about what information you need and why.\n"
            "2. Call exactly ONE tool to get that information.\n"
            "3. After receiving the result, analyze what you learned.\n"
            "4. Decide: do you need more data, or can you draw conclusions?\n"
            "5. When you have enough evidence, provide your full analysis "
            "WITHOUT calling any more tools.\n\n"
            f"## CRITICAL CONSTRAINTS\n"
            f"- You have a MAXIMUM of {MAX_TOOL_CALLS_PER_SUBTASK} tool calls for "
            f"this subtask. You have used {subtask.tool_calls_made} so far.\n"
            "- After 2-3 tool calls, STOP and synthesize your findings. Quality "
            "analysis of limited data beats shallow gathering of lots of data.\n"
            "- Do NOT call memory recall tools (recall_findings, recall_memories, "
            "recall_thoughts, recall_learnings, recall_tool_results) on a fresh "
            "database — they will return empty results and waste tool calls.  Only "
            "use recall tools if you have already stored findings in previous sessions.\n"
            "- Prefer search_news and search_web for gathering current information. "
            "Use get_market_data only for specific assets you are analyzing.\n"
            "- When you have gathered enough information, provide your COMPLETE "
            "analysis as your final response.  Include specific data points, "
            "percentages, and actionable insights.\n\n"
            "IMPORTANT:\n"
            "- Only call a tool when you have a specific reason to.\n"
            "- Always explain your reasoning BEFORE calling a tool.\n"
            "- Use store_finding to save important discoveries.\n"
            "- Be specific: name assets, prices, dates, percentages.\n"
            "- Never fabricate data — only state what the tools returned.\n"
        )

    # ------------------------------------------------------------------ #
    # Phase 3: Compile and Communicate
    # ------------------------------------------------------------------ #

    async def _compile_and_communicate(self, session: ResearchSession) -> None:
        """Synthesize all findings and send an email report."""
        await self._state_machine.transition_to(State.COMMUNICATING)

        # Gather all findings across subtasks
        all_findings: list[str] = []
        for st in session.subtasks:
            if st.findings:
                all_findings.append(
                    f"## {st.description}\n" + "\n".join(st.findings)
                )

        if not all_findings:
            # No direct findings — try to pull useful data from consciousness
            # tool results logged during this session
            tool_results_text = self._gather_session_tool_results(session)
            if tool_results_text:
                all_findings.append(
                    "## Research Data Gathered (from tool calls)\n"
                    + tool_results_text
                )
                self._log_stream(
                    "SYSTEM",
                    "No explicit findings, but recovered data from tool call "
                    "results — attempting report compilation.",
                )
            else:
                self._log_stream(
                    "SYSTEM",
                    f"Session #{session.session_id} complete with no actionable "
                    f"findings across {len(session.subtasks)} subtasks. "
                    f"Total tool calls: {sum(st.tool_calls_made for st in session.subtasks)}. "
                    "Next session will try different approaches.",
                )
                return

        self._log_stream(
            "RECOMMENDATION", "Compiling research report..."
        )

        enrichment = self._llm.get_context_enrichment()
        guidance = getattr(self._config, "guidance_prompt", "") or ""

        system_prompt = (
            "You are a professional investment research analyst writing a "
            "client-facing report. Your reader is a sophisticated investor "
            "who expects data-driven analysis.\n\n"
            f"{enrichment}\n\n"
            "STRICT RULES — violating ANY of these makes the report unusable:\n"
            "1. Write ONLY the finished report. Never include internal thoughts, "
            "planning language, or phrases like 'let me compile', 'I will now', "
            "'before sending', 'I have sufficient findings', 'let me store'. "
            "The reader is a client, NOT your inner monologue.\n"
            "2. Every claim must cite a specific data point: a price, percentage, "
            "date, volume figure, or named source. No vague statements like "
            "'the market looks promising' without numbers.\n"
            "3. The body must be at least 150 words of substantive analysis.\n"
            "4. If the research found nothing actionable, say so plainly with "
            "the data you checked — do NOT pad with filler.\n\n"
            "REPORT STRUCTURE (use this exact layout in the body):\n"
            "MARKET CONTEXT\n"
            "2-3 sentences on current conditions with specific prices/levels.\n\n"
            "KEY FINDINGS\n"
            "Numbered list. Each finding must include: what was found, "
            "the specific data (price, % change, volume, date), and the source "
            "(e.g. CoinGecko, Finnhub, news article title).\n\n"
            "RISK FACTORS\n"
            "Bullet list of concrete risks with data where possible.\n\n"
            "NEXT RESEARCH FOCUS\n"
            "1-2 sentences on what you will investigate next and why.\n\n"
            "Return a JSON object with this exact schema:\n"
            "```json\n"
            "{\n"
            '  "subject": "Concise, specific subject line with key ticker/insight",\n'
            '  "body": "The full report body as plain text (min 150 words, structured as above)",\n'
            '  "recommendations": [\n'
            "    {\n"
            '      "asset": "TICKER",\n'
            '      "direction": "buy|sell|hold|watch",\n'
            '      "confidence": 0.0,\n'
            '      "thesis": "1-2 sentence investment thesis with specific data",\n'
            '      "timeframe": "short-term|medium-term|long-term",\n'
            '      "evidence": ["specific data point 1", "data point 2"],\n'
            '      "risks": ["specific risk 1", "risk 2"],\n'
            '      "key_metrics": {"price": 0.0, "change_24h": "0%", "volume": "0"}\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n"
            "Only include recommendations when evidence genuinely warrants one. "
            "An empty recommendations list is fine.\n"
        )

        findings_text = "\n\n".join(all_findings)
        user_msg = (
            f"## User's Investment Focus\n{guidance}\n\n"
            f"## Raw Research Data\n{findings_text}\n\n"
            "Write the client-facing report now. Extract every specific "
            "price, percentage, and data point from the raw data above. "
            "Do NOT summarize vaguely — cite the numbers. "
            "Return ONLY the JSON object, nothing else."
        )

        try:
            response, _ = await self._llm.chat(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_msg}],
                tools=None,
                use_cache=False,
            )

            if response.thinking.strip():
                self._log_stream("THINKING", response.thinking.strip())

            report = _try_parse_json(response.thinking)
            if isinstance(report, dict) and "subject" in report:
                await self._send_report(report, session)
                session.findings_summary = report.get("body", "")[:500]
            else:
                # Fallback: use raw text as email body
                await self._send_report(
                    {
                        "subject": f"AEON Research Report — Session #{session.session_id}",
                        "body": response.thinking,
                        "recommendations": [],
                    },
                    session,
                )
                session.findings_summary = response.thinking[:500]

        except Exception as exc:
            self._log_stream("ERROR", f"Failed to compile report: {exc}")
            logger.exception("Report compilation failed")

    def _gather_session_tool_results(self, session: ResearchSession) -> str:
        """Try to recover useful data from consciousness tool results for this session."""
        if not hasattr(self._consciousness, "get_tool_results"):
            return ""
        try:
            results = self._consciousness.get_tool_results(
                cycle_id=session.session_id, limit=20
            )
            if not results:
                return ""
            parts = []
            for r in results:
                if isinstance(r, dict) and r.get("success"):
                    tool_name = r.get("tool_name", "unknown")
                    data = str(r.get("result", ""))[:500]
                    if data and data != "None":
                        parts.append(f"- {tool_name}: {data}")
            return "\n".join(parts)
        except Exception:
            return ""

    async def _send_report(
        self, report: dict[str, Any], session: ResearchSession
    ) -> None:
        """Send the compiled report via the send_research_update tool."""
        subject = report.get("subject", "AEON Research Report")
        body = report.get("body", "")
        recs = report.get("recommendations", [])

        if "send_research_update" in self._tools.list_tools():
            try:
                result = await self._tools.call(
                    "send_research_update",
                    subject=subject,
                    body=body,
                    recommendations=recs,
                )
                if isinstance(result, dict) and result.get("skipped"):
                    self._log_stream(
                        "SYSTEM",
                        f"Report rejected by quality gate: {result.get('reason', 'unknown')}. "
                        "Will gather more data before next report attempt.",
                    )
                elif isinstance(result, dict) and result.get("sent"):
                    self._log_stream(
                        "RECOMMENDATION",
                        f"Report sent: {subject}",
                    )
                elif isinstance(result, dict) and result.get("error"):
                    self._log_stream(
                        "ERROR",
                        f"Report email failed: {result['error']}",
                    )
                else:
                    self._log_stream(
                        "RECOMMENDATION",
                        f"Report dispatched: {subject}",
                    )
            except Exception as exc:
                self._log_stream(
                    "ERROR", f"Failed to send email: {exc}"
                )
        else:
            self._log_stream(
                "SYSTEM",
                "send_research_update tool not available — report not emailed",
            )

        # Store recommendations in consciousness
        for rec in recs:
            if hasattr(self._consciousness, "store_recommendation"):
                try:
                    self._consciousness.store_recommendation(rec)
                except Exception:
                    pass

    # ------------------------------------------------------------------ #
    # Phase 4: Plan Next Session
    # ------------------------------------------------------------------ #

    async def _plan_next_session(self, session: ResearchSession) -> str:
        """Ask the LLM what the next session should focus on."""
        enrichment = self._llm.get_context_enrichment()

        findings_summary = []
        for st in session.subtasks:
            if st.findings:
                findings_summary.append(
                    f"- {st.description}: {'; '.join(f[:200] for f in st.findings)}"
                )

        # Detect whether this session produced no findings
        session_had_findings = bool(findings_summary)
        total_tool_calls = sum(st.tool_calls_made for st in session.subtasks)

        no_findings_guidance = ""
        if not session_had_findings:
            no_findings_guidance = (
                "\n## IMPORTANT: This session produced NO actionable findings.\n"
                f"The agent made {total_tool_calls} tool calls across "
                f"{len(session.subtasks)} subtasks but found nothing useful.\n"
                "For the next session, you MUST try DIFFERENT approaches:\n"
                "- Use different search queries or data sources\n"
                "- Target different assets or sectors\n"
                "- Try broader or narrower research questions\n"
                "- If web search was rate-limited, rely more on market data tools\n"
                "- If market data returned errors, rely more on news search\n"
                "Do NOT repeat the same failed strategy.\n"
            )

        system_prompt = (
            "You are AEON, an AI hedge fund research manager.\n\n"
            f"{enrichment}\n\n"
            "Based on this session's findings, plan what the NEXT research "
            "session should focus on.  Identify:\n"
            "- Leads to follow up on\n"
            "- Gaps in the research\n"
            "- New opportunities to investigate\n"
            "- Whether to expand scope or go deeper\n\n"
            "Be specific and concise (2-4 sentences).\n"
            f"{no_findings_guidance}"
        )

        user_msg = (
            f"## This Session's Guidance\n{session.guidance}\n\n"
            f"## Findings\n" + "\n".join(findings_summary)
            if findings_summary
            else f"## This Session's Guidance\n{session.guidance}\n\n"
            f"## Findings\nNo significant findings from this session. "
            f"{total_tool_calls} tool calls were made but yielded no usable data."
        )

        try:
            response, _ = await self._llm.chat(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_msg}],
                tools=None,
                use_cache=False,
            )
            plan = response.thinking
            if plan.strip():
                self._log_stream("THINKING", plan.strip())
            if hasattr(self._consciousness, "store_thought"):
                self._consciousness.store_thought(
                    f"Next session plan: {plan}", importance=0.8
                )
            return plan
        except Exception as exc:
            self._log_stream("ERROR", f"Next session planning failed: {exc}")
            return ""

    # ------------------------------------------------------------------ #
    # Phase 5: Strategic Sleep
    # ------------------------------------------------------------------ #

    async def _strategic_sleep(self, session: ResearchSession) -> None:
        """Sleep between sessions, respecting budget and market hours.

        The sleep is interrupted immediately if new steering arrives or
        shutdown is requested, so the agent can act on user input without
        waiting for the full timer.
        """
        await self._state_machine.transition_to(State.SLEEPING)

        sleep_secs = self._compute_sleep_duration()

        plan_preview = session.next_session_plan[:100] if session.next_session_plan else "continuing research"
        self._log_stream(
            "SLEEPING",
            f"Sleeping {sleep_secs}s before next session. "
            f"Next: {plan_preview}",
        )

        self._steering_event.clear()

        shutdown_task = asyncio.create_task(self._shutdown_event.wait())
        steering_task = asyncio.create_task(self._steering_event.wait())
        try:
            done, pending = await asyncio.wait(
                {shutdown_task, steering_task},
                timeout=sleep_secs,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()
            if steering_task in done:
                self._log_stream(
                    "STEERING",
                    "Sleep interrupted — new steering received, starting next session immediately",
                )
        except asyncio.CancelledError:
            shutdown_task.cancel()
            steering_task.cancel()
            raise

    def _compute_sleep_duration(self) -> int:
        if self._llm.is_budget_exceeded():
            return SLEEP_COST_EXCEEDED

        now = datetime.now(timezone.utc)
        hour = now.hour

        any_market_open = False
        for _market, hours in MARKET_HOURS.items():
            open_h = hours["open"]
            close_h = hours["close"]
            if open_h <= close_h:
                if open_h <= hour < close_h:
                    any_market_open = True
            else:
                if hour >= open_h or hour < close_h:
                    any_market_open = True

        if not any_market_open:
            return SLEEP_MARKET_CLOSED

        return SLEEP_BETWEEN_SESSIONS

    # ------------------------------------------------------------------ #
    # Context building
    # ------------------------------------------------------------------ #

    async def _build_context(self) -> ResearchContext:
        enrichment = self._llm.get_context_enrichment()
        cost_summary = self._llm.get_cost_summary()

        recent_findings: list[dict[str, Any]] = []
        recent_recs: list[dict[str, Any]] = []
        research_summary: dict[str, Any] = {}
        consciousness_summary = ""
        latest_steering: str | None = None
        last_session_plan: str | None = None

        try:
            if hasattr(self._consciousness, "get_recent_findings"):
                recent_findings = self._consciousness.get_recent_findings(20)
            if hasattr(self._consciousness, "get_recommendations"):
                recent_recs = self._consciousness.get_recommendations(limit=10)
            if hasattr(self._consciousness, "get_research_summary"):
                research_summary = self._consciousness.get_research_summary(
                    hours=24
                )
            if hasattr(self._consciousness, "generate_context_prompt"):
                consciousness_summary = (
                    self._consciousness.generate_context_prompt()
                )
            if hasattr(self._consciousness, "get_latest_steering"):
                latest_steering = self._consciousness.get_latest_steering()
            if hasattr(self._consciousness, "get_last_session_plan"):
                last_session_plan = self._consciousness.get_last_session_plan()
        except Exception as exc:
            logger.warning("Error gathering consciousness context: %s", exc)

        guidance = ""
        if hasattr(self._config, "guidance_prompt"):
            guidance = self._config.guidance_prompt or ""

        return ResearchContext(
            current_time=datetime.now(timezone.utc).isoformat(),
            market_hours_status=(
                enrichment if isinstance(enrichment, str) else str(enrichment)
            ),
            daily_budget_remaining=cost_summary.get("budget_remaining", 1.0),
            daily_cost_so_far=cost_summary.get("daily_cost", 0.0),
            user_guidance=guidance,
            latest_steering=latest_steering,
            recent_findings=recent_findings,
            recent_recommendations=recent_recs,
            research_summary=research_summary,
            available_tools=[],
            cycle_number=self._session_count,
            consciousness_summary=consciousness_summary,
            last_session_plan=last_session_plan,
        )

    # ------------------------------------------------------------------ #
    # Persistence helpers
    # ------------------------------------------------------------------ #

    def _persist_session(self, session: ResearchSession) -> int:
        """Save or update a research session in consciousness."""
        if not hasattr(self._consciousness, "store_session"):
            return 0

        subtasks_data = [
            {
                "id": st.id,
                "description": st.description,
                "objective": st.objective,
                "status": st.status,
                "findings": st.findings,
                "tool_calls_made": st.tool_calls_made,
            }
            for st in session.subtasks
        ]

        if session.db_row_id:
            try:
                self._consciousness.update_session(
                    session.db_row_id,
                    status=session.status,
                    findings_summary=session.findings_summary,
                    next_plan=session.next_session_plan,
                    subtasks_json=json.dumps(subtasks_data, default=str),
                )
            except Exception:
                pass
            return session.db_row_id

        try:
            return self._consciousness.store_session({
                "session_id": session.session_id,
                "guidance": session.guidance,
                "subtasks": subtasks_data,
                "status": session.status,
                "findings_summary": session.findings_summary,
                "next_plan": session.next_session_plan,
            })
        except Exception:
            return 0

    # ------------------------------------------------------------------ #
    # Stream helper
    # ------------------------------------------------------------------ #

    def _log_stream(self, category: str, message: str) -> None:
        if self._stream is not None:
            if hasattr(self._stream, "log"):
                self._stream.log(category, message)
            elif hasattr(self._stream, "write"):
                self._stream.write(message, source="orchestrator")

    @staticmethod
    def _extract_cost(cost: Any) -> float:
        if isinstance(cost, (int, float)):
            return float(cost)
        if hasattr(cost, "actual") and cost.actual is not None:
            return float(cost.actual)
        if hasattr(cost, "estimated"):
            return float(cost.estimated)
        return 0.0


# ------------------------------------------------------------------ #
# JSON parsing helper
# ------------------------------------------------------------------ #


def _summarize_tool_result(result: Any, max_len: int = 200) -> str:
    """Produce a one-line summary of a tool execution result."""
    if not isinstance(result, dict):
        return str(result)[:max_len]
    if result.get("error"):
        return f"ERROR: {str(result['error'])[:max_len]}"
    data = result.get("result")
    if data is None:
        return "ok (no data)"
    text = str(data)
    if len(text) > max_len:
        return text[:max_len] + "…"
    return text


def _extract_intermediate_finding(tool_name: str, tool_data: Any) -> str:
    """Extract a concise finding from a successful tool result.

    Returns a brief summary string, or empty string if the data is not
    useful enough to record.
    """
    text = str(tool_data)
    if not text or text in ("None", "null", "{}", "[]", "ok"):
        return ""

    # Skip empty or trivial results
    if len(text) < 20:
        return ""

    # Truncate to a reasonable size for a finding
    summary = text[:800]
    if len(text) > 800:
        summary += "..."

    return f"[{tool_name}] {summary}"


def _try_parse_json(text: str) -> dict[str, Any] | list[Any] | None:
    """Extract JSON from LLM output, stripping markdown fences."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    if stripped.startswith(("{", "[")):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    for start_char, end_char in [("[", "]"), ("{", "}")]:
        start = stripped.find(start_char)
        end = stripped.rfind(end_char)
        if start != -1 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                continue

    return None
