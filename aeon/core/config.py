"""Configuration for the AEON Hedge Fund Manager.

Replaces the old tier-gated AeonConfig/Capability/TierGate system with a
unified ``HedgeFundConfig`` dataclass.  All settings load from environment
variables (``AEON_`` prefix) or a ``.env`` file in the project root.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# dotenv bootstrap
# ---------------------------------------------------------------------------

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None  # type: ignore[assignment]
else:
    load_dotenv()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _env(name: str, default: str = "") -> str:
    """Read an environment variable with a default."""
    return os.environ.get(name, default)


def _env_int(name: str, default: int = 0) -> int:
    """Read an int environment variable."""
    val = os.environ.get(name, "")
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        logger.warning("Config: could not parse %s=%r as int, using default %d", name, val, default)
        return default


def _env_float(name: str, default: float = 0.0) -> float:
    """Read a float environment variable."""
    val = os.environ.get(name, "")
    if not val:
        return default
    try:
        return float(val)
    except ValueError:
        logger.warning("Config: could not parse %s=%r as float, using default %f", name, val, default)
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable."""
    val = os.environ.get(name, "")
    if not val:
        return default
    return val.lower() in ("1", "true", "yes", "on")


def _env_list(name: str, default: list[str] | None = None) -> list[str]:
    """Parse a comma-separated list environment variable."""
    val = os.environ.get(name, "")
    if not val:
        return default or []
    return [item.strip() for item in val.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# HedgeFundConfig
# ---------------------------------------------------------------------------

@dataclass
class HedgeFundConfig:
    """Central configuration for the AEON Hedge Fund Manager.

    All fields have sensible defaults and can be overridden via environment
    variables (``AEON_`` prefix) or the :meth:`from_env` / :meth:`from_file`
    class methods.
    """

    # -- LLM Settings -------------------------------------------------------
    llm_provider: str = "ollama"  # ollama, bedrock, anthropic
    llm_model: str = "llama3.2"

    # Bedrock-specific
    bedrock_aws_access_key_id: str = ""
    bedrock_aws_secret_access_key: str = ""
    bedrock_aws_region: str = "us-east-1"
    bedrock_model_id: str = "anthropic.claude-3-sonnet-20240229-v1:0"

    # Ollama-specific
    ollama_host: str = "http://localhost:11434"

    # -- User Settings -------------------------------------------------------
    user_email: str = ""
    user_name: str = ""
    guidance_prompt: str = ""  # User's investment focus/strategy description

    # -- Research Settings ---------------------------------------------------
    research_budget_daily_usd: float = 1.00  # Max daily LLM spend
    market_focus: list[str] = field(default_factory=lambda: ["crypto", "stocks"])
    update_frequency_minutes: int = 30  # How often to send email updates when findings warrant
    max_research_depth: int = 10  # Max tool calls per research chain

    # -- Connector Settings --------------------------------------------------
    search_provider: str = "duckduckgo"  # duckduckgo, serpapi
    serpapi_key: str = ""
    brave_api_key: str = ""
    news_sources: list[str] = field(default_factory=lambda: ["web_search"])

    # -- Cost Management -----------------------------------------------------
    sleep_base_seconds: int = 120  # Base sleep between research cycles
    sleep_market_closed_seconds: int = 600  # Longer sleep when markets closed
    max_cycles_before_forced_sleep: int = 10  # Force sleep after N rapid cycles

    # -- Email / SMTP --------------------------------------------------------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = True
    email_sender: str = ""
    email_recipient: str = ""

    # -- IMAP (for receiving steering responses) -----------------------------
    imap_host: str = ""
    imap_user: str = ""
    imap_password: str = ""

    # -- Data directory ------------------------------------------------------
    data_dir: str = "data"

    # -- Restricted mode (human approval gating) -----------------------------
    restricted_mode: bool = False

    @classmethod
    def from_env(cls) -> HedgeFundConfig:
        """Build a config from environment variables.

        Environment variables use the ``AEON_`` prefix where possible,
        falling back to legacy names for backward compatibility.
        """
        return cls(
            # LLM
            llm_provider=_env("AEON_LLM_PROVIDER", "ollama"),
            llm_model=_env("AEON_LLM_MODEL", _env("OLLAMA_MODEL", "llama3.2")),
            bedrock_aws_access_key_id=_env("BEDROCK_AWS_ACCESS_KEY_ID"),
            bedrock_aws_secret_access_key=_env("BEDROCK_AWS_SECRET_ACCESS_KEY"),
            bedrock_aws_region=_env("BEDROCK_AWS_REGION", "us-east-1"),
            bedrock_model_id=_env("BEDROCK_MODEL_ID", "anthropic.claude-3-sonnet-20240229-v1:0"),
            ollama_host=_env("OLLAMA_HOST", "http://localhost:11434"),
            # User
            user_email=_env("AEON_USER_EMAIL"),
            user_name=_env("AEON_USER_NAME"),
            guidance_prompt=_env("AEON_GUIDANCE_PROMPT", ""),
            # Research
            research_budget_daily_usd=_env_float("AEON_RESEARCH_BUDGET_DAILY", 1.00),
            market_focus=_env_list("AEON_MARKET_FOCUS", ["crypto", "stocks"]),
            update_frequency_minutes=_env_int("AEON_UPDATE_FREQUENCY_MINUTES", 30),
            max_research_depth=_env_int("AEON_MAX_RESEARCH_DEPTH", 10),
            # Connectors
            search_provider=_env("AEON_SEARCH_PROVIDER", "duckduckgo"),
            serpapi_key=_env("SERPAPI_KEY"),
            brave_api_key=_env("BRAVE_API_KEY"),
            news_sources=_env_list("AEON_NEWS_SOURCES", ["web_search"]),
            # Cost management
            sleep_base_seconds=_env_int("AEON_SLEEP_BASE_SECONDS", 120),
            sleep_market_closed_seconds=_env_int("AEON_SLEEP_MARKET_CLOSED_SECONDS", 600),
            max_cycles_before_forced_sleep=_env_int("AEON_MAX_CYCLES_BEFORE_FORCED_SLEEP", 10),
            # Email / SMTP
            smtp_host=_env("AEON_SMTP_HOST", _env("AEON_APPROVAL_EMAIL_SMTP_HOST")),
            smtp_port=_env_int("AEON_SMTP_PORT", _env_int("AEON_APPROVAL_EMAIL_SMTP_PORT", 587)),
            smtp_user=_env("AEON_SMTP_USER", _env("AEON_APPROVAL_EMAIL_SENDER")),
            smtp_password=_env("AEON_SMTP_PASSWORD", _env("AEON_APPROVAL_EMAIL_PASSWORD")),
            smtp_use_tls=_env_bool("AEON_SMTP_USE_TLS", True),
            email_sender=_env("AEON_EMAIL_SENDER", _env("AEON_APPROVAL_EMAIL_SENDER")),
            email_recipient=_env("AEON_EMAIL_RECIPIENT", _env("AEON_APPROVAL_EMAIL_RECIPIENT")),
            # IMAP
            imap_host=_env("AEON_IMAP_HOST"),
            imap_user=_env("AEON_IMAP_USER"),
            imap_password=_env("AEON_IMAP_PASSWORD"),
            # Data directory
            data_dir=_env("AEON_DATA_DIR", "data"),
            # Restricted mode
            restricted_mode=_env_bool("AEON_RESTRICTED_MODE", False),
        )

    @classmethod
    def from_file(cls, path: str) -> HedgeFundConfig:
        """Load config from a ``.env`` file, then apply env var overrides.

        Args:
            path: Path to a ``.env`` file.

        Returns:
            A populated ``HedgeFundConfig``.
        """
        env_path = Path(path)
        if env_path.exists():
            # Parse .env manually (no dependency on python-dotenv at runtime)
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, _, value = line.partition("=")
                    key = key.strip()
                    value = value.strip().strip("\"'")
                    # Only set if not already in environment (env vars take precedence)
                    if key not in os.environ:
                        os.environ[key] = value
        else:
            logger.warning("Config: .env file not found at %s", path)

        return cls.from_env()

    @property
    def email_config(self) -> dict[str, Any]:
        """Return email configuration as a dict (backward compat)."""
        return {
            "smtp_host": self.smtp_host,
            "smtp_port": self.smtp_port,
            "sender_email": self.email_sender,
            "sender_password": self.smtp_password,
            "recipient_email": self.email_recipient,
            "use_tls": self.smtp_use_tls,
        }

    def validate(self) -> None:
        """Raise ``RuntimeError`` if restricted mode requires email but it is missing."""
        if not self.restricted_mode:
            return
        required = {"smtp_host": self.smtp_host, "email_sender": self.email_sender,
                     "smtp_password": self.smtp_password, "email_recipient": self.email_recipient}
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise RuntimeError(
                f"restricted_mode is enabled but email config is incomplete. "
                f"Missing: {', '.join(missing)}"
            )

    def has_search(self) -> bool:
        """True if a web search provider is available.

        DuckDuckGo is always available without an API key.
        """
        return True

    def has_email(self) -> bool:
        """True if SMTP email sending is configured."""
        return bool(self.smtp_host and self.email_sender and self.smtp_password)

    def has_imap(self) -> bool:
        """True if IMAP email receiving is configured."""
        return bool(self.imap_host and self.imap_user and self.imap_password)


# ---------------------------------------------------------------------------
# CapabilityRegistry
# ---------------------------------------------------------------------------

class CapabilityRegistry:
    """Tracks which external capabilities are available based on env vars.

    Each capability maps to one or more environment variables that must be
    present (non-empty) for the capability to be considered available.
    """

    _CAPABILITY_MAP: dict[str, tuple[str, ...]] = {
        "email": ("AEON_SMTP_HOST", "AEON_EMAIL_SENDER", "AEON_SMTP_PASSWORD"),
        "imap": ("AEON_IMAP_HOST", "AEON_IMAP_USER", "AEON_IMAP_PASSWORD"),
        "serpapi_search": ("SERPAPI_KEY",),
        "brave_search": ("BRAVE_API_KEY",),
        "bedrock_llm": ("BEDROCK_AWS_ACCESS_KEY_ID", "BEDROCK_AWS_SECRET_ACCESS_KEY"),
        "ollama_llm": (),  # always available
        "duckduckgo_search": (),  # always available
    }

    @classmethod
    def is_available(cls, capability: str) -> bool:
        """Return True if *capability* is configured.

        Args:
            capability: The capability name (e.g. ``"email"``).

        Returns:
            True when every required environment variable is non-empty.
        """
        required = cls._CAPABILITY_MAP.get(capability, ())
        if not required:
            return True
        return all(os.environ.get(var, "").strip() for var in required)

    @classmethod
    def check_all(cls) -> dict[str, bool]:
        """Return availability for every registered capability."""
        return {cap: cls.is_available(cap) for cap in cls._CAPABILITY_MAP}

    @classmethod
    def register_capability(cls, name: str, *env_vars: str) -> None:
        """Register a new capability and its required environment variables."""
        cls._CAPABILITY_MAP[name] = env_vars

    @classmethod
    def missing_vars(cls, capability: str) -> list[str]:
        """Return the list of missing environment variables for a capability."""
        required = cls._CAPABILITY_MAP.get(capability, ())
        return [var for var in required if not os.environ.get(var, "").strip()]

    @classmethod
    def log_status(cls) -> None:
        """Log the availability status of all registered capabilities."""
        for cap, available in cls.check_all().items():
            level = logging.INFO if available else logging.WARNING
            logger.log(level, "Capability '%s': %s", cap, "available" if available else "unavailable")


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_config: HedgeFundConfig | None = None


def get_config() -> HedgeFundConfig:
    """Return the global :class:`HedgeFundConfig` singleton.

    On first call, loads from environment variables.  Subsequent calls return
    the same instance.
    """
    global _config
    if _config is None:
        _config = HedgeFundConfig.from_env()
    return _config


def reset_config() -> None:
    """Reset the global config singleton (useful for testing)."""
    global _config
    _config = None
