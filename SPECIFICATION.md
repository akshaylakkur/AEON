# Project AEON: Autonomous Economic Operating Node

## Version
1.0.0

## Overview

AEON is a persistent AI research agent that operates in a continuous loop: plan research, execute tool calls, analyze findings, synthesize investment theses, and communicate insights to its operator via email. It does not execute trades, manage portfolios, or interact with exchanges. It is a research brain — an autonomous analyst that never sleeps.

The system runs locally or in a container. It connects to an LLM (Ollama for free local inference, or AWS Bedrock for cloud), ingests market data from public APIs, searches the web for intelligence, and delivers professional HTML research reports to the operator's inbox. The operator can steer the agent's focus at any time via the CLI, the interactive TUI, or by replying to an email.

---

## Core Principles

1. **Research, Not Trading**: AEON investigates and recommends. It never places orders, holds positions, or moves money. The operator makes all execution decisions.
2. **LLM-First Reasoning**: Every strategic decision — what to research, which tool to call next, whether a finding is significant, how to frame a recommendation — flows through the LLM. There is no hard-coded strategy logic.
3. **Cost-Aware Operation**: Every LLM token and API call is tracked against a configurable daily budget. When the budget is exhausted, the agent sleeps until the next day. Sleep intervals are also market-aware — shorter during trading hours when findings are active, longer when markets are closed.
4. **Persistent Memory**: All research sessions, findings, theses, recommendations, and steering inputs are stored in a SQLite database that survives restarts. The agent picks up where it left off.

---

## System Architecture

### Subsystems

| Subsystem | Package | Purpose |
|-----------|---------|---------|
| **Core** | `aeon/core/` | Event bus, state machine, configuration, consciousness database, neural orchestrator, consciousness stream |
| **Cortex** | `aeon/cortex/` | LLM providers (Ollama, Bedrock), unified LLM client, reasoning engine, tool registry, planner, executor |
| **Tools** | `aeon/tools/` | 31 research tools registered via `@register_tool` decorator, organized by category |
| **Senses** | `aeon/senses/` | Data connectors — market data (CoinGecko, Yahoo Finance, Binance, Coinbase, Finnhub, Alpha Vantage), web intelligence (DuckDuckGo, SerpAPI, Brave), sentiment |
| **Limbs** | `aeon/limbs/` | Output interfaces — SMTP email client, IMAP listener for steering responses, notification formatting, HTML templates |
| **Ledger** | `aeon/ledger/` | Cost tracking, daily budget enforcement, burn rate analysis |
| **Analytics** | `aeon/analytics/` | Alpha generation scoring, risk assessment, backtesting framework |
| **Security** | `aeon/security/` | Encrypted credential vault, spend caps, file sandboxing, audit trail |
| **Metamind** | `aeon/metamind/` | Self-analysis, adaptation engine, strategy journaling, research pattern evaluation |
| **Reflexes** | `aeon/reflexes/` | Circuit breakers, API health monitoring, failover logic |
| **Simulation** | `aeon/simulation/` | Simulated market data and tool responses for testing without live APIs |
| **TUI** | `aeon/tui/` | Interactive terminal interface built with Textual — live consciousness stream, steering input |
| **Orchestrator** | `aeon/orchestrator/` | Main `HedgeFundManager` class that wires all subsystems together, plus the `UserCommunicationLayer` for email digests |

### State Machine

The agent cycles through six operational states:

```
INITIALIZING -> PLANNING -> RESEARCHING -> ANALYZING -> COMMUNICATING -> SLEEPING -> PLANNING -> ...
```

- **INITIALIZING**: Load config, connect to LLM, register tools, open consciousness database.
- **PLANNING**: The LLM decomposes the current research objective into 2-6 concrete subtasks.
- **RESEARCHING**: Execute subtasks sequentially. Each subtask makes one tool call per turn, up to 8 calls per subtask and 10 subtasks per session.
- **ANALYZING**: Evaluate accumulated findings. Score them for significance. Generate or update investment theses.
- **COMMUNICATING**: Compile findings into a professional HTML email report and send it to the operator.
- **SLEEPING**: Pause before the next session. Duration depends on market hours, finding activity, and remaining daily budget.
- **STEERING**: Injected when the operator sends input via CLI, TUI, or email reply. The guidance is stored in consciousness and shapes the next planning phase.
- **SHUTDOWN**: Graceful exit — flush logs, close database, revoke running tasks.

Any state may transition to SHUTDOWN.

---

## Research Tools

31 tools across 5 categories, all registered via a decorator-based registry that auto-generates parameter schemas from type hints and docstrings:

### Market Data (5 tools)
- `get_market_data` — Current price, volume, market cap for any symbol (crypto or stock)
- `get_market_overview` — Broad market snapshot across asset classes
- `get_price_history` — Historical OHLCV data for technical analysis
- `get_stock_fundamentals` — Earnings, P/E, revenue for equities
- `get_crypto_details` — On-chain metrics, supply data, exchange listings

### Intelligence & Research (4 tools)
- `web_search` — General web search via DuckDuckGo, SerpAPI, or Brave
- `get_news` — Aggregated financial news for a topic or ticker
- `scrape_page` — Extract content from a specific URL
- `search_reddit` — Reddit discussion analysis for sentiment and catalysts

### Communication (3 tools)
- `send_research_update` — Email a formatted research report to the operator
- `send_urgent_alert` — High-priority email for time-sensitive findings
- `check_user_responses` — Poll IMAP for steering replies from the operator

### Analysis & Insights (9 tools)
- `get_research_history` — Review past sessions and findings
- `get_spending_report` — Daily/weekly cost breakdown
- `get_burn_rate` — Projected budget runway
- `analyze_risk` — Risk assessment for a position or thesis
- `get_financial_summary` — Portfolio-level analysis summary
- `get_market_calendar` — Upcoming earnings, events, catalysts
- `compare_assets` — Side-by-side comparison of multiple symbols
- `get_correlation_data` — Cross-asset correlation analysis
- `get_sector_analysis` — Sector-level performance and rotation data

### Memory & Persistence (10 tools)
- `store_finding` / `recall_findings` — Save and retrieve research findings
- `store_thesis` / `recall_theses` — Manage investment theses with conviction scores
- `store_memory` / `recall_memories` — General knowledge persistence
- `get_transaction_history` — Review past tool call history and costs
- `store_strategy_entry` / `recall_strategy_entries` — Long-form strategic thinking
- `clear_stale_memories` — Prune old or low-value entries

---

## Configuration

All configuration is via environment variables with the `AEON_` prefix, loaded from a `.env` file. Key settings:

| Variable | Default | Purpose |
|----------|---------|---------|
| `AEON_LLM_PROVIDER` | `ollama` | LLM backend: `ollama` (local, free) or `bedrock` (AWS cloud) |
| `AEON_LLM_MODEL` | `llama3.2` | Model name for the selected provider |
| `AEON_GUIDANCE_PROMPT` | *(empty)* | The operator's investment focus — what to research |
| `AEON_RESEARCH_BUDGET_DAILY` | `1.00` | Maximum daily LLM spend in USD |
| `AEON_SEARCH_PROVIDER` | `duckduckgo` | Web search backend: `duckduckgo` (free), `serpapi`, or `brave` |
| `AEON_MARKET_FOCUS` | `crypto,stocks` | Comma-separated asset classes to prioritize |
| `AEON_UPDATE_FREQUENCY_MINUTES` | `30` | Minimum interval between email reports |
| `AEON_SLEEP_BASE_SECONDS` | `120` | Base sleep between research cycles |
| `AEON_MAX_RESEARCH_DEPTH` | `10` | Maximum tool calls per research chain |
| `AEON_SMTP_HOST` | *(empty)* | SMTP server for sending email reports |
| `AEON_IMAP_HOST` | *(empty)* | IMAP server for receiving steering responses |

See `.env.example` for the complete list including Bedrock credentials, Finnhub/Alpha Vantage API keys, and Yahoo Finance toggle.

---

## Consciousness & Memory Model

AEON maintains a persistent SQLite database (`data/consciousness.db`) with the following tables:

- **research_sessions** — Timestamped records of each plan-research-analyze-communicate cycle, including subtask breakdown and findings summary
- **findings** — Structured market insights: ticker, thesis, confidence score, source, timestamp
- **recommendations** — Investment recommendations with directional bias, conviction level, entry/exit reasoning
- **steering_inputs** — Operator guidance captured from CLI, TUI, or email
- **memories** — General knowledge: learnings, observations, tool result summaries
- **thoughts** — LLM reasoning traces for debugging and self-analysis
- **decisions** — Action decisions with outcomes for pattern learning
- **strategy_entries** — Long-form strategic thinking and meta-cognition

The consciousness stream (`data/consciousness.log`) provides a real-time, human-readable feed of agent activity, categorized as `[PLANNING]`, `[RESEARCH]`, `[FINDING]`, `[RECOMMENDATION]`, `[TOOL_CALL]`, `[SLEEPING]`, `[THINKING]`, `[STEERING]`.

---

## Market Data Routing

The `MarketDataRouter` selects the best available provider with automatic failover:

- **Crypto**: Coinbase -> Binance -> CoinGecko
- **Stocks**: Finnhub -> Alpha Vantage -> Yahoo Finance

All market data connectors are optional. If no stock API keys are configured, AEON operates in crypto-only mode using free APIs. The router detects asset type from the symbol and routes to the appropriate provider chain.

---

## LLM Integration

AEON supports two LLM providers through a unified `LLMClient` interface:

### Ollama (Local, Free)
- Runs locally via the Ollama daemon
- No API costs — ideal for continuous research loops
- Compatible with any model Ollama supports (Llama, Mistral, Qwen, etc.)

### AWS Bedrock (Cloud)
- Claude, Llama, Mistral, and other models via AWS
- Token usage tracked against the daily budget
- Automatic cost calculation per request

The `LLMReasoner` wraps the client with research-specific methods: `reason()` for general reasoning, `reason_structured()` for JSON-formatted output, `research_reasoning()` for multi-step analysis, and `generate_recommendation()` for investment thesis synthesis.

---

## User Interaction

### CLI (`aeonctl`)
```
aeonctl                  Launch interactive TUI
aeonctl start -d         Run as background daemon
aeonctl status           Show research status
aeonctl steer "..."      Send steering input
aeonctl log -f           Stream consciousness log
aeonctl history          View findings and recommendations
aeonctl config           Show configuration
aeonctl stop             Graceful shutdown
```

### TUI
A Textual-based terminal interface with:
- Live consciousness stream (scrolling feed of agent thinking)
- Steering input bar (type guidance and press Enter)
- Status indicators (current state, session count, budget remaining)

### Email
- **Outbound**: HTML research reports with findings, theses, and recommendations
- **Inbound**: Reply to any report email with steering input — the IMAP listener picks it up and feeds it into the next research cycle

---

## Installation

```bash
git clone https://github.com/akshaylakkur/AEON.git
cd AEON
bash install.sh
```

The installer is a 5-phase wizard:
1. **Preflight** — Verify Python 3.11+, check system dependencies
2. **Dependencies** — Create virtualenv, install packages, register `aeonctl` globally
3. **Configure** — Walk through LLM provider, email, search, market data, and budget setup
4. **Verify** — Validate LLM connectivity and tool registration
5. **Ready** — Display usage instructions and offer to start the agent

---

## Testing

```bash
.venv/bin/python -m pytest
```

Tests use `pytest-asyncio` with `asyncio_mode = "auto"`. All external services (LLM, HTTP APIs, email, market data) are mocked. The simulation subsystem provides a full mock environment for integration testing without live API calls.

---

## Requirements

- Python 3.11+
- macOS or Linux
- Ollama (local) or AWS Bedrock credentials
- Optional: Finnhub, Alpha Vantage, SerpAPI, or Brave API keys for extended data coverage

---

## License

GPL-3.0
