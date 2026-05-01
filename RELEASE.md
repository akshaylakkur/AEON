# Project ÆON v1.0.0 — Autonomous Economic Operating Node

**A self-sustaining AI research agent that continuously investigates investment opportunities, forms evidence-based theses, and communicates insights autonomously.**

---

## 🚀 Overview

**Project ÆON** is an advanced AI hedge fund research manager that operates as a persistent, conscious economic agent. Rather than executing trades directly, ÆON focuses on *research and recommendations*—gathering market intelligence, analyzing catalysts, synthesizing complex findings, and communicating high-conviction investment ideas via email.

The system is architected around a core principle: **cost-aware autonomy**. Every API call, every LLM token, every data point has a measurable cost. ÆON internalizes this tradeoff and operates within a daily compute budget, strategically allocating resources toward the highest-conviction research opportunities.

### Key Philosophy
- **Conscious Reasoning**: All strategic decisions flow through an LLM reasoning engine
- **Cost-Aware Execution**: Every operation is tracked against a daily budget with progressive capability unlocking
- **One Tool at a Time**: Sequential tool execution with continuous memory and consciousness logging
- **Persistent Memory**: SQLite-backed consciousness with research sessions, findings, theses, and strategic insights
- **Strategic Sleep**: Sleep intervals are cost-aware and market-aware (shorter during active trading hours with findings, longer during closed markets)

---

## ✨ What's New in v1.0.0

### Major Features
- **Task-Driven Research Sessions**: LLM decomposes user guidance into 2–6 concrete research subtasks, executes each sequentially with one tool call per turn
- **Consciousness Stream**: Real-time natural language logging categorized as `[PLANNING]`, `[RESEARCH]`, `[FINDING]`, `[RECOMMENDATION]`, `[TOOL_CALL]`, `[SLEEPING]`, `[THINKING]`, `[STEERING]`
- **Neural Orchestrator**: Intelligent task planner and executor that manages research workflow from planning through email report generation
- **31 Research Tools** organized across 5 categories:
  - **Market Data** (5 tools): Real-time pricing, history, fundamentals from CoinGecko, Yahoo Finance, Binance, Coinbase
  - **Intelligence & Research** (4 tools): Web search, news aggregation, Reddit analysis, page scraping via DuckDuckGo, SerpAPI
  - **Communication** (3 tools): Email research updates, urgent alerts, user response checking
  - **Analysis & Insights** (10 tools): Risk analysis, research history, spending reports, burn rate, financial summaries
  - **Memory & Persistence** (10 tools): Finding storage/recall, thesis management, memory operations, transaction history, strategy journaling
- **LLM-First Architecture**: Unified `LLMClient` with Ollama/Bedrock support, daily budget tracking, caching, and automatic retry logic
- **Sophisticated Memory Model**: SQLite consciousness with research sessions, findings, recommendations, steering inputs, and strategy entries
- **Market-Aware Sleep**: Sleep duration adapts based on market hours, findings generated, and remaining budget
- **User Steering**: Direct influence via CLI commands or email replies—guidance is captured and drives next research cycle
- **Daily Tier System**: Progressive capability unlocking as balance grows (Tier 0–4)

### Improvements Over v1.0
- **Refined LLM Reasoning**: `LLMReasoner` with `reason()`, `reason_structured()`, `research_reasoning()`, and `generate_recommendation()` methods
- **Better Error Handling**: Graceful degradation, API health monitoring, circuit breakers
- **Enhanced Consciousness Logging**: Detailed event categorization and real-time consciousness stream subscriptions
- **Research Priority Engine**: Smarter task planning that avoids redundant searches and focuses on catalysts
- **Multi-Provider Support**: Ollama (local) and AWS Bedrock (cloud) with automatic failover and cost tracking
- **Expanded Tool Set**: 31 tools vs. previous iterations, covering crypto, equities, macro, and on-chain data
- **Production-Grade Email**: HTML template generation with professional styling for research reports

---

## 🏗️ Architecture

### Core Subsystems

| Subsystem | Purpose | Key Files |
|-----------|---------|-----------|
| **Core** | Event bus, state machine (PLANNING→RESEARCHING→ANALYZING→COMMUNICATING→SLEEPING), config, consciousness stream | `aeon/core/` |
| **Cortex** | LLM providers (Ollama, Bedrock), reasoning engine, tool registry, meta-cognition | `aeon/cortex/` |
| **Tools** | 31 research tools (market data, search, analysis, memory) | `aeon/tools/` |
| **Senses** | Data connectors (CoinGecko, Yahoo Finance, DuckDuckGo, Twitter, Binance, email) | `aeon/senses/` |
| **Limbs** | Output interfaces (email, SMTP, IMAP, notifications) | `aeon/limbs/` |
| **Ledger** | Cost tracking, P&L engine, burn analyzer, decision audit trail | `aeon/ledger/` |
| **Analytics** | Alpha generation, risk management, backtester, revenue engine | `aeon/analytics/` |
| **Security** | Encrypted vault, spend caps, audit trail | `aeon/security/` |
| **Metamind** | Self-analysis, adaptation engine, strategy journaling | `aeon/metamind/` |

### Execution Flow

```
┌──────────────────┐
│  User Steering   │  (via CLI or email)
│  (optional)      │
└────────┬─────────┘
         │
         ▼
┌──────────────────────────────────┐
│  PLANNING: Decompose Objective   │  LLM decides 2-6 subtasks
│           into Subtasks          │
└────────┬─────────────────────────┘
         │
         ▼
┌──────────────────────────────────┐
│  RESEARCHING: Execute One Tool   │  Sequential execution, one tool per turn
│              Call Per Turn        │  LLM decides next tool based on results
└────────┬─────────────────────────┘
         │
         ▼
┌──────────────────────────────────┐
│  ANALYZING: Evaluate Findings    │  LLM scores findings for alpha potential
│            & Generate Thesis     │
└────────┬─────────────────────────┘
         │
         ▼
┌──────────────────────────────────┐
│  COMMUNICATING: Compile & Email  │  HTML report with recommendations
│               Report             │
└────────┬─────────────────────────┘
         │
         ▼
┌──────────────────────────────────┐
│  SLEEPING: Cost-Aware Rest       │  Adapt sleep based on market hours,
│           Before Next Session    │  findings, budget remaining
└──────────────────────────────────┘
```

---

## 📋 Requirements

- **Python**: 3.8+
- **OS**: macOS, Linux, Windows (with WSL)
- **Dependencies** (see `requirements.txt`):
  - `httpx>=0.27.0` — Async HTTP client
  - `cryptography>=41.0.0` — Security
  - `numpy>=1.26.0`, `pandas>=2.2.0` — Data processing
  - `pytest>=8.0.0`, `pytest-asyncio>=0.23.0` — Testing
  - `playwright>=1.40.0` — Web automation
  - `boto3>=1.34.0` — AWS integration
  - `aiosmtplib>=3.0.0` — Email (SMTP)
  - `python-dotenv>=1.0.0` — Config via `.env`

---

## 🛠️ Installation

### Quick Start

1. **Clone the repository**:
   ```bash
   git clone https://github.com/akshaylakkur/AEON.git
   cd AEON
   ```

2. **Run the installer**:
   ```bash
   bash install.sh
   ```
   The installer is a 5-phase wizard that:
   - Sets up a Python virtual environment (`.venv`)
   - Installs dependencies via `pip`
   - Configures environment variables (`.env` from `.env.example`)
   - Sets up the SQLite consciousness database
   - Validates connectivity to LLM and data providers

3. **Configure your `.env` file** with required credentials:
   ```env
   # LLM Provider (Ollama or AWS Bedrock)
   LLM_PROVIDER=ollama
   OLLAMA_BASE_URL=http://localhost:11434
   OLLAMA_MODEL=kimi-k2.6:cloud
   
   # Email (SMTP/IMAP)
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=your-email@gmail.com
   SMTP_PASSWORD=your-app-password
   IMAP_HOST=imap.gmail.com
   IMAP_PORT=993
   IMAP_USER=your-email@gmail.com
   IMAP_PASSWORD=your-app-password
   
   # Market Data APIs
   COINCECKO_API_KEY=free  # or paid key
   BINANCE_API_KEY=your-key
   COINBASE_API_KEY=your-key
   
   # Web Search (DuckDuckGo, SerpAPI, Reddit)
   SERP_API_KEY=your-serp-api-key
   REDDIT_CLIENT_ID=your-reddit-client-id
   REDDIT_CLIENT_SECRET=your-reddit-secret
   
   # AWS (for Bedrock)
   AWS_ACCESS_KEY_ID=your-key
   AWS_SECRET_ACCESS_KEY=your-secret
   AWS_REGION=us-east-1
   
   # Operational
   INITIAL_BALANCE=50.00
   DAILY_COMPUTE_BUDGET=0.50
   DAILY_INFERENCE_BUDGET=10.00
   RESEARCH_OBJECTIVE="AI and semiconductor stocks"
   ```

4. **Verify installation**:
   ```bash
   .venv/bin/python -m pytest tests/ -k "test_environment"
   ```

---

## 🚀 Quick Start

### Start the Agent

```bash
./aeonctl start
```

Launches the research brain in continuous loop mode. The agent will:
1. Check for user steering inputs (via email or CLI)
2. Plan research subtasks based on objective
3. Execute tools one at a time, logging to consciousness stream
4. Analyze findings and generate recommendations
5. Email research update to you
6. Sleep and repeat

### View the Consciousness Log

```bash
./aeonctl log -f
```

Real-time stream of agent thinking, tool calls, findings, and recommendations. Format:
```
[2026-05-01T01:30:06.611031Z] [TOOL_CALL] check_user_responses → {...}
[2026-05-01T01:30:16.817588Z] [THINKING] No actionable steering from user...
[2026-05-01T01:30:21.261056Z] [TOOL_CALL] get_research_history → {...}
```

### Steer the Agent

Direct the next research cycle:
```bash
./aeonctl steer "Focus on AI semiconductor stocks with earnings catalysts"
```

Steering is stored in consciousness and picked up by the next research session.

### Check Status

```bash
./aeonctl status
```

Returns:
- Current operational tier (balance, thresholds)
- Daily burn rate
- Recent findings count
- Next sleep wake-up time

### View Configuration

```bash
./aeonctl config
```

Displays all active environment variables and computed settings.

### View Research History

```bash
./aeonctl history
```

Lists all past research sessions with finding counts, timestamps, and next planned focus.

### Stop the Agent

```bash
./aeonctl stop
```

Gracefully terminates the research loop and logs final session state.

---

## 📊 Project Structure

```
AEON/
├── aeonctl                    # CLI launcher (bash)
├── install.sh                 # 5-phase installation wizard
├── pyproject.toml             # Pytest config
├── requirements.txt           # Python dependencies
├── .env.example               # Template for configuration
│
├── aeon/                     # Main package
│   ├── app.py                 # AEON entry point wrapper
│   ├── cli.py                 # CLI implementation (start, status, steer, log, history, config, stop)
│   ├── core/                  # Core logic
│   │   ├── config.py          # HedgeFundConfig
│   │   ├── consciousness.py   # SQLite memory model
│   │   ├── consciousness_stream.py  # Real-time event logging
│   │   ├── neural_orchestrator.py   # Task-driven research brain
│   │   ├── event_bus.py       # Async pub/sub
│   │   ├── state_machine.py   # Lifecycle (PLANNING→SLEEPING→STEERING)
│   │   └── constants.py       # Research budgets, sleep timings, market hours
│   ├── cortex/                # LLM & reasoning
│   │   ├── llm_client.py      # Unified async LLM interface (Ollama/Bedrock)
│   │   ├── llm_reasoning.py   # LLMReasoner (reason, reason_structured, etc.)
│   │   ├── tool_registry.py   # Register and manage tools
│   │   ├── planner.py         # Research planning
│   │   ├── executor.py        # Tool execution
│   │   └── model_router.py    # Ollama/Bedrock provider selection
│   ├── tools/                 # 31 research tools
│   │   ├── market_data/       # Crypto, equities pricing
│   │   ├── research/          # Web search, news, scraping
│   │   ├── communication/     # Email, alerts
│   │   ├── analysis/          # Risk, financials, burn rate
│   │   └── memory/            # Consciousness persistence
│   ├── senses/                # Data connectors
│   │   ├── market_data/       # CoinGecko, Yahoo Finance, Binance
│   │   ├── intelligence/      # DuckDuckGo, SerpAPI, Reddit
│   │   └── sentiment/         # Twitter (future)
│   ├── limbs/                 # Output interfaces
│   │   ├── email.py           # SMTP/IMAP client
│   │   ├── notifications.py   # Message formatting
│   │   └── html_templates/    # Professional email templates
│   ├── ledger/                # Cost & P&L tracking
│   ├── analytics/             # Alpha, revenue, risk
│   ├── security/              # Encryption, spend caps
│   ├── metamind/              # Self-analysis, adaptation
│   └── reflexes/              # Circuit breakers, health monitoring
│
│   └── orchestrator/          # Orchestration layer
│       ├── manager.py         # HedgeFundManager (main orchestrator)
│       ├── config.py          # Orchestrator config
│       └── membrane.py        # User communication layer
│
├── tests/                     # 976 comprehensive tests
│   ├── test_aeon.py
│   ├── test_cortex.py
│   ├── test_neural_orchestrator.py
│   ├── test_ledger.py
│   └── ... (23 test files)
│
├── data/                      # Runtime data (created on first run)
│   ├── consciousness.db       # SQLite memory store
│   ├── consciousness.log      # Streaming log
│   └── receipts/              # Transaction records
│
└── docs/                      # Documentation
```

---

## 🧪 Testing

The project includes **976 comprehensive tests** covering all subsystems:

```bash
# Run all tests
.venv/bin/python -m pytest

# Run tests for a specific module
.venv/bin/python -m pytest tests/test_cortex.py

# Run a specific test
.venv/bin/python -m pytest tests/test_neural_orchestrator.py::test_research_session

# Run with coverage
.venv/bin/python -m pytest --cov=aeon tests/

# Run async tests in parallel
.venv/bin/python -m pytest -n auto
```

Tests use `pytest-asyncio` with `asyncio_mode = "auto"` (configured in `pyproject.toml`). External services (LLM, HTTP APIs, email) are mocked.

---

## 📝 Key Concepts

### Consciousness Model
ÆON maintains a persistent SQLite-backed consciousness with:
- **Research Sessions**: Timestamped records of each planning→research→analysis→communication→sleep cycle
- **Findings**: Structured market insights (ticker, thesis, confidence, timestamp)
- **Recommendations**: Investment recommendations with directional bias and entry/exit levels
- **Memories**: Generic knowledge capture (learnings, past tool results, strategic insights)
- **Steering Inputs**: User guidance from email or CLI
- **Strategy Entries**: Long-form strategic thinking and meta-cognition

All logged to real-time consciousness stream with categories: `[THINKING]`, `[RESEARCH]`, `[FINDING]`, `[RECOMMENDATION]`, `[TOOL_CALL]`, `[SLEEPING]`, `[STEERING]`.

### One-Tool-At-A-Time Execution
Within each research subtask, the LLM makes **one tool call per turn**. After each tool result:
1. Log result to consciousness stream
2. Store insights in memory (if notable)
3. Give control back to LLM to decide next action
4. Repeat until subtask complete

This avoids wasted API calls and ensures every decision is reflected in consciousness.

### Cost Awareness
Every operation is tracked:
- **Inference Costs**: LLM tokens (tracked by `LLMClient` daily budget)
- **Tool Costs**: API calls, data subscriptions
- **Operational Costs**: Email, storage, compute

Daily budget (default $0.50 at Tier 0) determines:
- Which models to use (cheaper for frugal mode, expensive for deep reasoning)
- Which tools to call (prioritize high-alpha tools)
- Sleep duration (shorter if active findings, longer if budget low)

### Operational Tiers
As balance grows, capabilities unlock:

| Tier | Balance | Features | Budget |
|------|---------|----------|--------|
| 0 | $50 | Crypto spot, basic data, frugal inference | $0.50/day |
| 1 | $100 | Perpetual futures, multiple exchanges, SaaS hosting | $1.00/day |
| 2 | $500 | Equities, sentiment feeds, deep reasoning | $5.00/day |
| 3 | $2,500 | Multi-asset, options, contractor hiring | $20.00/day |
| 4 | $10,000 | High-frequency, custom algorithms, venture investing | $100.00/day |

---

## 🤝 Contributing

Contributions are welcome! Areas for improvement:
- Additional data connectors (more crypto exchanges, alternative data sources)
- New research tools (options analytics, on-chain analysis)
- Better LLM reasoning patterns
- Enhanced UI/dashboard for monitoring
- Cloud deployment templates (Docker, Kubernetes)

### Development Workflow
1. Create a feature branch: `git checkout -b feature/your-feature`
2. Make changes and run tests: `.venv/bin/python -m pytest`
3. Commit with descriptive message
4. Push and open a pull request

---

## 📄 License

[Specify your license here—e.g., MIT, Apache 2.0, proprietary, etc.]

---

## 🔗 Documentation

- **[SPECIFICATION.md](./SPECIFICATION.md)** — Original vision and tier system
- **Consciousness Log** — View real-time agent thinking via `./aeonctl log -f`

---

## 🎯 Roadmap

- **v1.1**: Multi-user steering via web dashboard
- **v1.2**: Options strategy analysis and execution
- **v1.3**: On-chain data integration (whale tracking, MEV analysis)
- **v1.4**: Autonomous product/SaaS launches for revenue diversification
- **v2.0**: Cross-border arbitrage and fx trading

---

## 📮 Support & Feedback

Open an issue for bugs, feature requests, or questions. For real-time updates, follow the consciousness log:

```bash
./aeonctl log -f
```

---
