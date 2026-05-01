#!/usr/bin/env bash
# =============================================================================
# AEON AI Hedge Fund Manager -- Installation Script
# =============================================================================
# Usage:
#   bash install.sh
#
# Works on macOS and Linux.  Python 3.11+ required.
# Safe to run multiple times -- idempotent by design.
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------
RED='\033[0;31m';    GREEN='\033[0;32m';    YELLOW='\033[0;33m'
BLUE='\033[0;34m';   MAGENTA='\033[0;35m';  CYAN='\033[0;36m'
BOLD='\033[1m';      DIM='\033[2m';          RESET='\033[0m'

red()    { echo -e "${RED}$*${RESET}"; }
green()  { echo -e "${GREEN}$*${RESET}"; }
yellow() { echo -e "${YELLOW}$*${RESET}"; }
cyan()   { echo -e "${CYAN}$*${RESET}"; }
bold()   { echo -e "${BOLD}$*${RESET}"; }
dim()    { echo -e "${DIM}$*${RESET}"; }

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
AEON_HOME="${AEON_HOME:-}"

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
banner() {
    echo
    echo -e "${CYAN}  ================================================================${RESET}"
    echo -e "${CYAN}  |${RESET}  ${BOLD}AEON -- AI Hedge Fund Research Manager${RESET}                     ${CYAN}|${RESET}"
    echo -e "${CYAN}  |${RESET}            ${DIM}Installation & Configuration${RESET}                      ${CYAN}|${RESET}"
    echo -e "${CYAN}  ================================================================${RESET}"
    echo
    echo -e "  AEON is an autonomous AI research agent that:"
    echo -e "    ${GREEN}*${RESET} Continuously researches investment opportunities"
    echo -e "    ${GREEN}*${RESET} Forms evidence-based investment theses"
    echo -e "    ${GREEN}*${RESET} Sends detailed recommendations to you via email"
    echo -e "    ${GREEN}*${RESET} Accepts steering input to focus on what matters to you"
    echo
}

# ---------------------------------------------------------------------------
# Phase 1 -- Pre-flight checks
# ---------------------------------------------------------------------------
phase1_preflight() {
    echo -e "${BOLD}${MAGENTA}Phase 1/5 -- Pre-flight checks${RESET}"
    echo

    OS="unknown"
    case "$(uname -s)" in
        Darwin)  OS="macos" ;;
        Linux)   OS="linux" ;;
        *) red "Unsupported OS.  macOS or Linux required."; exit 1 ;;
    esac
    echo -e "  ${GREEN}ok${RESET} OS: ${BOLD}${OS}${RESET}"

    PYTHON=""
    for candidate in python3 python; do
        if cmd="$(\command -v "$candidate" 2>/dev/null)"; then
            ver="$("$cmd" -c 'import sys; print(sys.version_info[:2])' 2>/dev/null || true)"
            case "$ver" in
                "(3, 11)"|"(3, 12)"|"(3, 13)"|"(3, 14)"|"(3, 15)")
                    PYTHON="$cmd"; break ;;
            esac
        fi
    done

    if [[ -z "$PYTHON" ]]; then
        red "Python 3.11+ is required but was not found."
        if [[ "$OS" == "macos" ]]; then
            echo "  Install it:  brew install python@3.12"
        else
            echo "  Install it:  sudo apt update && sudo apt install -y python3.12 python3.12-venv python3-pip"
        fi
        exit 1
    fi
    echo -e "  ${GREEN}ok${RESET} Python: ${BOLD}$("$PYTHON" --version)${RESET}"

    if ! "$PYTHON" -m pip --version &>/dev/null; then
        red "pip is not available.  Install python3-pip."
        exit 1
    fi
    echo -e "  ${GREEN}ok${RESET} pip: available"

    echo
}

# ---------------------------------------------------------------------------
# Helper: install aeonctl globally
# ---------------------------------------------------------------------------
_install_global_aeonctl() {
    # The venv's pip install -e . creates .venv/bin/aeonctl which is the
    # canonical console script.  We need to make it reachable from $PATH.
    #
    # Strategy (in order of preference):
    #   1. Symlink .venv/bin/aeonctl → ~/.local/bin/aeonctl  (no sudo)
    #   2. Symlink .venv/bin/aeonctl → /usr/local/bin/aeonctl (needs sudo)
    #   3. Create a tiny wrapper script in ~/.local/bin/
    #   4. Fall back to shell profile PATH addition
    #
    # We link the *venv* aeonctl (the pip console script), not the bash
    # launcher, so that it always resolves the correct Python + package.

    local AEONCTL_BIN="$AEON_HOME/.venv/bin/aeonctl"

    if [[ ! -x "$AEONCTL_BIN" ]]; then
        echo -e "  ${YELLOW}..${RESET} aeonctl console script not found in venv -- skipping global install"
        echo -e "  ${DIM}You can still run it with: $AEON_HOME/.venv/bin/aeonctl${RESET}"
        return
    fi

    # --- Try ~/.local/bin first (no sudo needed) ---
    local LOCAL_BIN="$HOME/.local/bin"
    mkdir -p "$LOCAL_BIN" 2>/dev/null || true

    if [[ -d "$LOCAL_BIN" ]]; then
        ln -sf "$AEONCTL_BIN" "$LOCAL_BIN/aeonctl" 2>/dev/null
        if [[ -x "$LOCAL_BIN/aeonctl" ]]; then
            echo -e "  ${GREEN}ok${RESET} aeonctl symlinked to ${DIM}$LOCAL_BIN/aeonctl${RESET}"

            # Ensure ~/.local/bin is in PATH
            if ! echo "$PATH" | tr ':' '\n' | grep -qx "$LOCAL_BIN"; then
                _add_to_shell_path "$LOCAL_BIN"
            else
                echo -e "  ${GREEN}ok${RESET} $LOCAL_BIN is already in PATH"
            fi
            return
        fi
    fi

    # --- Fallback: try /usr/local/bin (may need sudo) ---
    local GLOBAL_BIN="/usr/local/bin/aeonctl"
    if [[ -L "$GLOBAL_BIN" ]] || [[ ! -e "$GLOBAL_BIN" ]]; then
        if ln -sf "$AEONCTL_BIN" "$GLOBAL_BIN" 2>/dev/null; then
            echo -e "  ${GREEN}ok${RESET} aeonctl symlinked to ${DIM}/usr/local/bin/aeonctl${RESET}"
            return
        fi
    fi

    # --- Last resort: add venv bin to PATH via shell profile ---
    echo -e "  ${YELLOW}..${RESET} Could not symlink aeonctl to a directory in PATH"
    _add_to_shell_path "$AEON_HOME/.venv/bin"
}

_add_to_shell_path() {
    local BIN_DIR="$1"
    local ADDED=false

    # Detect user shell and append to the appropriate profile
    local SHELL_NAME
    SHELL_NAME="$(basename "${SHELL:-/bin/bash}")"

    local PROFILES=()
    case "$SHELL_NAME" in
        zsh)  PROFILES=("$HOME/.zshrc" "$HOME/.zprofile") ;;
        bash) PROFILES=("$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile") ;;
        *)    PROFILES=("$HOME/.profile") ;;
    esac

    local EXPORT_LINE="export PATH=\"$BIN_DIR:\$PATH\""

    for profile in "${PROFILES[@]}"; do
        if [[ -f "$profile" ]]; then
            # Check if already present
            if grep -qF "$BIN_DIR" "$profile" 2>/dev/null; then
                echo -e "  ${GREEN}ok${RESET} $BIN_DIR already in ${DIM}$profile${RESET}"
                ADDED=true
                break
            fi
            # Append
            echo "" >> "$profile"
            echo "# Added by AEON installer" >> "$profile"
            echo "$EXPORT_LINE" >> "$profile"
            echo -e "  ${GREEN}ok${RESET} Added $BIN_DIR to PATH in ${DIM}$profile${RESET}"
            ADDED=true
            break
        fi
    done

    if [[ "$ADDED" == "false" ]]; then
        # Create the first profile file
        local target="${PROFILES[0]}"
        echo "" >> "$target"
        echo "# Added by AEON installer" >> "$target"
        echo "$EXPORT_LINE" >> "$target"
        echo -e "  ${GREEN}ok${RESET} Created ${DIM}$target${RESET} with PATH update"
    fi

    echo -e "  ${YELLOW}>>>${RESET} ${BOLD}Restart your terminal${RESET} or run: ${CYAN}source ${PROFILES[0]}${RESET}"
    echo -e "  ${DIM}Then 'aeonctl' will be available globally.${RESET}"
}

# ---------------------------------------------------------------------------
# Phase 2 -- Environment & dependencies
# ---------------------------------------------------------------------------
phase2_deps() {
    echo -e "${BOLD}${MAGENTA}Phase 2/5 -- Dependencies${RESET}"
    echo

    # Detect project root
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
    if [[ -n "${SCRIPT_DIR:-}" ]] && [[ -f "$SCRIPT_DIR/aeon/app.py" ]]; then
        AEON_HOME="$SCRIPT_DIR"
        echo -e "  ${GREEN}ok${RESET} Running from local project: ${DIM}$AEON_HOME${RESET}"
    elif [[ -z "$AEON_HOME" ]]; then
        AEON_HOME="$HOME/.aeon"
    fi

    cd "$AEON_HOME"

    # Virtual environment
    if [[ ! -d ".venv" ]]; then
        echo -e "  ${YELLOW}..${RESET} Creating virtual environment..."
        "$PYTHON" -m venv .venv
    fi
    VENV_PYTHON=".venv/bin/python"
    VENV_PIP=".venv/bin/pip"

    "$VENV_PIP" install --upgrade pip setuptools wheel -q

    if [[ -f requirements.txt ]]; then
        echo -e "  ${YELLOW}..${RESET} Installing Python packages..."
        "$VENV_PIP" install -r requirements.txt -q
        echo -e "  ${GREEN}ok${RESET} Packages installed"
    fi

    # Install the aeon package in editable mode (registers aeonctl console script)
    if [[ -f pyproject.toml ]]; then
        echo -e "  ${YELLOW}..${RESET} Installing aeon package (editable)..."
        "$VENV_PIP" install -e . -q
        echo -e "  ${GREEN}ok${RESET} aeon package installed"
    fi

    mkdir -p data
    echo -e "  ${GREEN}ok${RESET} Runtime directories ready"

    # Make the bash launcher executable
    chmod +x "$AEON_HOME/aeonctl" 2>/dev/null || true

    # Install aeonctl globally so it's available from any directory.
    # Strategy: try multiple locations in order of preference.
    _install_global_aeonctl

    echo
}

# ---------------------------------------------------------------------------
# Phase 3 -- Configuration wizard
# ---------------------------------------------------------------------------
phase3_configure() {
    echo -e "${BOLD}${MAGENTA}Phase 3/5 -- Configuration${RESET}"
    echo

    cd "$AEON_HOME"
    ENV_FILE="$AEON_HOME/.env"

    # Seed .env from template
    if [[ ! -f "$ENV_FILE" ]]; then
        if [[ -f ".env.example" ]]; then
            cp .env.example "$ENV_FILE"
        else
            touch "$ENV_FILE"
        fi
    fi

    _set_env() {
        local var="$1" raw="$2"
        local val="$raw"
        if [[ "$val" == *[[:space:]]* ]]; then
            val="\"$val\""
        fi
        if grep -q "^${var}=" "$ENV_FILE" 2>/dev/null; then
            grep -v "^${var}=" "$ENV_FILE" > "$ENV_FILE.tmp" || true
            echo "${var}=${val}" >> "$ENV_FILE.tmp"
            mv "$ENV_FILE.tmp" "$ENV_FILE"
        else
            echo "${var}=${val}" >> "$ENV_FILE"
        fi
    }

    # Only run interactive wizard if we have a TTY
    if [[ ! -t 0 ]]; then
        echo -e "  ${YELLOW}..${RESET} Non-interactive mode -- using defaults."
        echo -e "  ${DIM}Edit .env to configure: $ENV_FILE${RESET}"
        echo
        return
    fi

    # --- LLM Provider ---
    _choose_llm_provider
    _validate_provider

    # --- Email Configuration ---
    _configure_email

    # --- Research Focus ---
    _ask_guidance_prompt

    # --- Search Provider ---
    _configure_search

    # --- Market Data Sources ---
    _configure_market_data

    # --- Daily Budget ---
    _configure_budget

    echo
    echo -e "  ${GREEN}ok${RESET} Configuration saved to ${DIM}$ENV_FILE${RESET}"
}

_choose_llm_provider() {
    echo
    echo -e "  ${CYAN}-- LLM Provider Selection --${RESET}"
    echo
    echo -e "  AEON needs an LLM to think, plan, and generate recommendations."
    echo
    echo -e "  ${BOLD}Available providers:${RESET}"
    echo
    echo -e "  ${CYAN}[1]${RESET} ${BOLD}Ollama${RESET} (local, free)"
    echo -e "      Runs entirely on your machine. No API keys needed."
    echo -e "      ${DIM}https://ollama.com${RESET}"
    echo
    echo -e "  ${CYAN}[2]${RESET} ${BOLD}Amazon Bedrock${RESET} (cloud API)"
    echo -e "      AWS-managed models (Claude, Llama, etc.)."
    echo -e "      ${DIM}https://console.aws.amazon.com/bedrock${RESET}"
    echo
    echo -ne "  ${YELLOW}Choose [1-2, default 1]:${RESET} "
    read -r provider_choice

    case "${provider_choice:-1}" in
        1)
            echo
            echo -e "  ${GREEN}ok${RESET} Selected: ${BOLD}Ollama${RESET} (local)"
            echo
            echo -ne "  Ollama host [${DIM}http://localhost:11434${RESET}]: "
            read -r ollama_host
            [[ -n "$ollama_host" ]] && _set_env "OLLAMA_HOST" "$ollama_host"
            echo -ne "  Model name [${DIM}llama3.2${RESET}]: "
            read -r ollama_model
            [[ -n "$ollama_model" ]] && _set_env "OLLAMA_MODEL" "$ollama_model"
            _set_env "AEON_LLM_PROVIDER" "ollama"
            echo
            echo -e "  ${DIM}Make sure Ollama is running and the model is pulled:${RESET}"
            echo -e "  ${DIM}  ollama pull ${ollama_model:-llama3.2}${RESET}"
            ;;
        2)
            echo
            echo -e "  ${GREEN}ok${RESET} Selected: ${BOLD}Amazon Bedrock${RESET}"
            echo
            echo -ne "  AWS Access Key ID: "
            read -r bedrock_access_key
            [[ -n "$bedrock_access_key" ]] && _set_env "BEDROCK_AWS_ACCESS_KEY_ID" "$bedrock_access_key"
            echo -ne "  AWS Secret Access Key: "
            read -r bedrock_secret_key
            [[ -n "$bedrock_secret_key" ]] && _set_env "BEDROCK_AWS_SECRET_ACCESS_KEY" "$bedrock_secret_key"
            echo -ne "  AWS Region [${DIM}us-east-1${RESET}]: "
            read -r bedrock_region
            [[ -n "$bedrock_region" ]] && _set_env "BEDROCK_AWS_REGION" "$bedrock_region"
            echo -ne "  Model ID [${DIM}anthropic.claude-3-sonnet-20240229-v1:0${RESET}]: "
            read -r bedrock_model
            [[ -n "$bedrock_model" ]] && _set_env "BEDROCK_MODEL_ID" "$bedrock_model"
            _set_env "AEON_LLM_PROVIDER" "bedrock"
            echo
            echo -e "  ${GREEN}ok${RESET} Bedrock configured"
            ;;
    esac
}

_validate_provider() {
    echo
    echo -e "  ${BOLD}Validating LLM connectivity...${RESET}"
    echo

    local provider
    provider="$(grep "^AEON_LLM_PROVIDER=" "$ENV_FILE" | cut -d= -f2- || true)"
    [[ -z "$provider" ]] && provider="ollama"

    local success=false
    local retries=0
    local max_retries=2

    while [[ "$success" == "false" && "$retries" -lt "$max_retries" ]]; do
        case "$provider" in
            ollama)
                local host model
                host="$(grep "^OLLAMA_HOST=" "$ENV_FILE" | cut -d= -f2- || true)"
                model="$(grep "^OLLAMA_MODEL=" "$ENV_FILE" | cut -d= -f2- || true)"
                [[ -z "$host" ]] && host="http://localhost:11434"
                [[ -z "$model" ]] && model="llama3.2"

                echo -e "  ${YELLOW}..${RESET} Pinging Ollama at ${DIM}${host}${RESET} (model: ${DIM}${model}${RESET})..."

                if "$VENV_PYTHON" -c "
import asyncio, sys
from aeon.cortex.ollama_provider import OllamaProvider

async def test():
    p = OllamaProvider(host='${host}', model='${model}')
    ok = await p.health_check()
    if not ok:
        return False
    resp = await p.infer('Say hello in one word.')
    return True

result = asyncio.run(test())
sys.exit(0 if result else 1)
" 2>/dev/null; then
                    success=true
                else
                    retries=$((retries + 1))
                    echo -e "  ${RED}x${RESET} Ollama unreachable or model not found."
                    if [[ "$retries" -lt "$max_retries" ]]; then
                        echo -e "  ${YELLOW}..${RESET} Retrying in 2s..."
                        sleep 2
                    fi
                fi
                ;;
            bedrock)
                local ak sk region model_id
                ak="$(grep "^BEDROCK_AWS_ACCESS_KEY_ID=" "$ENV_FILE" | cut -d= -f2- || true)"
                sk="$(grep "^BEDROCK_AWS_SECRET_ACCESS_KEY=" "$ENV_FILE" | cut -d= -f2- || true)"
                region="$(grep "^BEDROCK_AWS_REGION=" "$ENV_FILE" | cut -d= -f2- || true)"
                model_id="$(grep "^BEDROCK_MODEL_ID=" "$ENV_FILE" | cut -d= -f2- || true)"
                [[ -z "$region" ]] && region="us-east-1"
                [[ -z "$model_id" ]] && model_id="anthropic.claude-3-sonnet-20240229-v1:0"

                echo -e "  ${YELLOW}..${RESET} Testing Bedrock in ${DIM}${region}${RESET}..."

                if "$VENV_PYTHON" -c "
import asyncio, sys
from aeon.cortex.bedrock_provider import BedrockProvider

async def test():
    p = BedrockProvider(
        access_key_id='${ak}',
        secret_access_key='${sk}',
        region='${region}',
        model_id='${model_id}'
    )
    resp = await p.infer('Say hello in one word.')
    return True

result = asyncio.run(test())
sys.exit(0 if result else 1)
" 2>/dev/null; then
                    success=true
                else
                    retries=$((retries + 1))
                    echo -e "  ${RED}x${RESET} Bedrock call failed."
                    if [[ "$retries" -lt "$max_retries" ]]; then
                        echo -e "  ${YELLOW}..${RESET} Retrying in 2s..."
                        sleep 2
                    fi
                fi
                ;;
            *)
                echo -e "  ${YELLOW}..${RESET} Unknown provider '${provider}' -- skipping validation."
                success=true
                ;;
        esac
    done

    if [[ "$success" == "false" ]]; then
        echo
        echo -e "  ${RED}x${RESET} LLM validation failed."
        echo -e "  ${YELLOW}..${RESET} You can fix this later by editing .env and running install.sh again."
        echo -e "  ${DIM}Continuing installation...${RESET}"
    else
        echo -e "  ${GREEN}ok${RESET} LLM is responsive."
    fi
}

_configure_email() {
    echo
    echo -e "  ${CYAN}-- Email Configuration --${RESET}"
    echo
    echo -e "  AEON sends research updates and recommendations via email."
    echo -e "  You can also reply to emails to steer the agent's research."
    echo
    echo -ne "  Configure email now? [Y/n] "
    read -r do_email
    if [[ "$do_email" == "n" || "$do_email" == "N" ]]; then
        echo -e "  ${DIM}Skipping email. You can configure it later in .env${RESET}"
        return
    fi

    # Gmail preset
    echo
    echo -ne "  Use Gmail preset? [Y/n] "
    read -r use_gmail
    if [[ "$use_gmail" != "n" && "$use_gmail" != "N" ]]; then
        _set_env "AEON_SMTP_HOST" "smtp.gmail.com"
        _set_env "AEON_SMTP_PORT" "587"
        _set_env "AEON_IMAP_HOST" "imap.gmail.com"
        echo -e "  ${GREEN}ok${RESET} Gmail SMTP/IMAP hosts configured."
        echo
        echo -e "  ${BOLD}Gmail App Password Required${RESET}"
        echo -e "  ${DIM}Go to: https://myaccount.google.com/apppasswords${RESET}"
        echo -e "  ${DIM}Create an app password for 'Mail' and paste it below.${RESET}"
        echo
    else
        echo -ne "  SMTP Host (e.g., smtp.gmail.com): "
        read -r smtp_host
        [[ -n "$smtp_host" ]] && _set_env "AEON_SMTP_HOST" "$smtp_host"
        echo -ne "  SMTP Port [${DIM}587${RESET}]: "
        read -r smtp_port
        [[ -n "$smtp_port" ]] && _set_env "AEON_SMTP_PORT" "$smtp_port"

        echo -ne "  IMAP Host (e.g., imap.gmail.com) [${DIM}skip${RESET}]: "
        read -r imap_host
        [[ -n "$imap_host" ]] && _set_env "AEON_IMAP_HOST" "$imap_host"
    fi

    echo -ne "  Your email address: "
    read -r email_addr
    if [[ -n "$email_addr" ]]; then
        _set_env "AEON_EMAIL_SENDER" "$email_addr"
        _set_env "AEON_SMTP_USER" "$email_addr"
        _set_env "AEON_IMAP_USER" "$email_addr"
        _set_env "AEON_USER_EMAIL" "$email_addr"
    fi

    echo -ne "  Email password (app password for Gmail): "
    read -rs email_pass
    echo
    if [[ -n "$email_pass" ]]; then
        _set_env "AEON_SMTP_PASSWORD" "$email_pass"
        _set_env "AEON_IMAP_PASSWORD" "$email_pass"
    fi

    echo -ne "  Recipient email (where updates go) [${DIM}same as above${RESET}]: "
    read -r recipient
    if [[ -n "$recipient" ]]; then
        _set_env "AEON_EMAIL_RECIPIENT" "$recipient"
    elif [[ -n "$email_addr" ]]; then
        _set_env "AEON_EMAIL_RECIPIENT" "$email_addr"
    fi

    echo -e "  ${GREEN}ok${RESET} Email configured"

    # Send a test email to verify SMTP credentials
    echo
    echo -e "  ${YELLOW}..${RESET} Sending test email to verify credentials..."

    local _test_ok=false
    while [[ "$_test_ok" == "false" ]]; do
        # Source current .env values and strip quotes
        local _smtp_host _smtp_port _smtp_user _smtp_pass _smtp_tls _from _to
        _smtp_host="$(grep "^AEON_SMTP_HOST=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | sed -e 's/^"//; s/"$//' | sed -e "s/^'//; s/'$//" || true)"
        _smtp_port="$(grep "^AEON_SMTP_PORT=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | sed -e 's/^"//; s/"$//' | sed -e "s/^'//; s/'$//" || true)"
        _smtp_user="$(grep "^AEON_SMTP_USER=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | sed -e 's/^"//; s/"$//' | sed -e "s/^'//; s/'$//" || true)"
        _smtp_pass="$(grep "^AEON_SMTP_PASSWORD=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | sed -e 's/^"//; s/"$//' | sed -e "s/^'//; s/'$//" || true)"
        _from="$(grep "^AEON_EMAIL_SENDER=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | sed -e 's/^"//; s/"$//' | sed -e "s/^'//; s/'$//" || true)"
        _to="$(grep "^AEON_EMAIL_RECIPIENT=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- | sed -e 's/^"//; s/"$//' | sed -e "s/^'//; s/'$//" || true)"
        _smtp_port="${_smtp_port:-587}"

        if AEON_SMTP_HOST="$_smtp_host" \
           AEON_SMTP_PORT="$_smtp_port" \
           AEON_SMTP_USER="$_smtp_user" \
           AEON_SMTP_PASSWORD="$_smtp_pass" \
           AEON_EMAIL_SENDER="$_from" \
           AEON_EMAIL_RECIPIENT="$_to" \
           "$VENV_PYTHON" -c '
import asyncio, os, aiosmtplib
from email.mime.text import MIMEText

async def send_test():
    msg = MIMEText(
        "If you received this email, AEON is correctly configured to send you research updates.\n\n"
        "You can reply to future research emails to steer the agent focus.\n\n"
        "— AEON Research Manager",
        "plain", "utf-8",
    )
    msg["Subject"] = "[AEON] Test Email — Setup Successful"
    msg["From"] = f"AEON Research <{os.environ['"'"'AEON_EMAIL_SENDER'"'"']}>"
    msg["To"] = os.environ['"'"'AEON_EMAIL_RECIPIENT'"'"']
    await aiosmtplib.send(
        msg,
        hostname=os.environ['"'"'AEON_SMTP_HOST'"'"'],
        port=int(os.environ.get('"'"'AEON_SMTP_PORT'"'"', "587")),
        username=os.environ['"'"'AEON_SMTP_USER'"'"'],
        password=os.environ['"'"'AEON_SMTP_PASSWORD'"'"'],
        start_tls=True,
    )

asyncio.run(send_test())
' 2>&1; then
            echo -e "  ${GREEN}ok${RESET} Test email sent to ${_to}"
            _test_ok=true
        else
            echo -e "  ${RED}FAILED${RESET} Could not send test email."
            echo
            echo -ne "  Retry with different credentials? [Y/n] "
            read -r retry_email
            if [[ "$retry_email" == "n" || "$retry_email" == "N" ]]; then
                echo -e "  ${YELLOW}..${RESET} Skipping email verification. You can fix .env later."
                _test_ok=true
            else
                echo -ne "  Your email address: "
                read -r email_addr
                if [[ -n "$email_addr" ]]; then
                    _set_env "AEON_EMAIL_SENDER" "$email_addr"
                    _set_env "AEON_SMTP_USER" "$email_addr"
                    _set_env "AEON_IMAP_USER" "$email_addr"
                    _set_env "AEON_USER_EMAIL" "$email_addr"
                fi
                echo -ne "  Email password (app password for Gmail): "
                read -rs email_pass
                echo
                if [[ -n "$email_pass" ]]; then
                    _set_env "AEON_SMTP_PASSWORD" "$email_pass"
                    _set_env "AEON_IMAP_PASSWORD" "$email_pass"
                fi
                echo -ne "  Recipient email [${DIM}${email_addr:-same}${RESET}]: "
                read -r recipient
                if [[ -n "$recipient" ]]; then
                    _set_env "AEON_EMAIL_RECIPIENT" "$recipient"
                elif [[ -n "$email_addr" ]]; then
                    _set_env "AEON_EMAIL_RECIPIENT" "$email_addr"
                fi
                echo -e "  ${YELLOW}..${RESET} Retrying..."
            fi
        fi
    done
}

_ask_guidance_prompt() {
    echo
    echo -e "  ${CYAN}-- Investment Focus / Guidance --${RESET}"
    echo
    echo -e "  Tell AEON what to research. This is your investment thesis and focus."
    echo
    echo -e "  ${DIM}Examples:${RESET}"
    echo -e "    - \"Focus on AI and semiconductor stocks, moderate risk appetite\""
    echo -e "    - \"Research crypto DeFi protocols and emerging L2 chains\""
    echo -e "    - \"Conservative value investing: find undervalued blue-chip stocks\""
    echo -e "    - \"Monitor NVDA, TSLA, and AAPL for swing trading opportunities\""
    echo
    local default_prompt="General market research: explore opportunities across stocks and crypto, moderate risk appetite."
    echo -ne "  Guidance prompt [${DIM}${default_prompt}${RESET}]: "
    read -r guidance_prompt
    if [[ -z "$guidance_prompt" ]]; then
        guidance_prompt="$default_prompt"
    fi
    _set_env "AEON_GUIDANCE_PROMPT" "$guidance_prompt"
    echo -e "  ${GREEN}ok${RESET} Guidance prompt saved"
}

_configure_search() {
    echo
    echo -e "  ${CYAN}-- Search Provider --${RESET}"
    echo
    echo -e "  AEON uses web search for research. Choose your primary search provider:"
    echo
    echo -e "  ${CYAN}[1]${RESET} ${BOLD}DuckDuckGo${RESET} (free, no key needed)"
    echo -e "      Free and works out of the box. Can be rate-limited under heavy use."
    echo
    echo -e "  ${CYAN}[2]${RESET} ${BOLD}SerpAPI${RESET} (paid, requires API key)"
    echo -e "      More reliable results and higher rate limits. 100 free searches/month."
    echo -e "      ${DIM}https://serpapi.com/manage-api-key${RESET}"
    echo
    echo -e "  ${CYAN}[3]${RESET} ${BOLD}Brave Search${RESET} (paid, requires API key)"
    echo -e "      Fast, privacy-focused search API. 2000 free queries/month."
    echo -e "      ${DIM}https://brave.com/search/api/${RESET}"
    echo
    echo -ne "  Choose [1-3, default 1]: "
    read -r search_choice

    case "${search_choice:-1}" in
        1)
            _set_env "AEON_SEARCH_PROVIDER" "duckduckgo"
            echo -e "  ${GREEN}ok${RESET} Using DuckDuckGo (free)"
            ;;
        2)
            _set_env "AEON_SEARCH_PROVIDER" "serpapi"
            echo
            echo -ne "  Do you have a SerpAPI key? [y/N] "
            read -r has_serpapi
            if [[ "$has_serpapi" == "y" || "$has_serpapi" == "Y" ]]; then
                echo -ne "  SerpAPI key: "
                read -r serpapi_key
                [[ -n "$serpapi_key" ]] && _set_env "SERPAPI_KEY" "$serpapi_key"
                echo -e "  ${GREEN}ok${RESET} Using SerpAPI"
            else
                echo -e "  ${YELLOW}..${RESET} No key provided. Get one at: https://serpapi.com/manage-api-key"
                echo -e "  ${DIM}Falling back to DuckDuckGo until you add SERPAPI_KEY to .env${RESET}"
                _set_env "AEON_SEARCH_PROVIDER" "duckduckgo"
            fi
            ;;
        3)
            _set_env "AEON_SEARCH_PROVIDER" "brave"
            echo
            echo -ne "  Do you have a Brave Search API key? [y/N] "
            read -r has_brave
            if [[ "$has_brave" == "y" || "$has_brave" == "Y" ]]; then
                echo -ne "  Brave Search API key: "
                read -r brave_key
                [[ -n "$brave_key" ]] && _set_env "BRAVE_API_KEY" "$brave_key"
                echo -e "  ${GREEN}ok${RESET} Using Brave Search"
            else
                echo -e "  ${YELLOW}..${RESET} No key provided. Get one at: https://brave.com/search/api/"
                echo -e "  ${DIM}Falling back to DuckDuckGo until you add BRAVE_API_KEY to .env${RESET}"
                _set_env "AEON_SEARCH_PROVIDER" "duckduckgo"
            fi
            ;;
    esac

    # --- Optional additional data sources ---
    echo
    echo -e "  ${CYAN}-- Optional: Additional Data Sources --${RESET}"
    echo
    echo -e "  These are optional API keys that enhance AEON's research capabilities."
    echo -e "  All are optional -- AEON works without them using free alternatives."
    echo

    # Brave Search as supplementary source (only ask if not already the primary)
    local current_search
    current_search="$(grep "^AEON_SEARCH_PROVIDER=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)"
    if [[ "$current_search" != "brave" ]]; then
        echo -ne "  Do you have a Brave Search API key (supplementary search)? [y/N] "
        read -r has_brave_extra
        if [[ "$has_brave_extra" == "y" || "$has_brave_extra" == "Y" ]]; then
            echo -ne "  Brave Search API key: "
            read -r brave_extra_key
            [[ -n "$brave_extra_key" ]] && _set_env "BRAVE_API_KEY" "$brave_extra_key"
            echo -e "  ${GREEN}ok${RESET} Brave Search key saved"
        else
            echo -e "  ${DIM}Skipped.${RESET}"
        fi
        echo
    fi

    # Twitter/X Bearer Token for sentiment analysis
    echo -ne "  Do you have a Twitter/X Bearer Token (for sentiment analysis)? [y/N] "
    read -r has_twitter
    if [[ "$has_twitter" == "y" || "$has_twitter" == "Y" ]]; then
        echo -ne "  Twitter/X Bearer Token: "
        read -r twitter_token
        [[ -n "$twitter_token" ]] && _set_env "TWITTER_BEARER_TOKEN" "$twitter_token"
        echo -e "  ${GREEN}ok${RESET} Twitter/X token saved"
    else
        echo -e "  ${DIM}Skipped. AEON will research without social sentiment data.${RESET}"
    fi
}

_configure_market_data() {
    echo
    echo -e "  ${CYAN}-- Market Data Sources --${RESET}"
    echo
    echo -e "  ${BOLD}Crypto data${RESET} is always available for free via:"
    echo -e "    ${GREEN}*${RESET} CoinGecko (primary)"
    echo -e "    ${GREEN}*${RESET} Binance (fallback)"
    echo -e "    ${GREEN}*${RESET} Coinbase (fallback)"
    echo
    echo -e "  ${BOLD}Stock/ETF data${RESET} providers (all optional, configure any combination):"
    echo
    echo -e "  ${CYAN}[1]${RESET} ${BOLD}Finnhub${RESET} (free API key, 60 requests/min) -- ${BOLD}recommended${RESET}"
    echo -e "      Real-time US stock quotes, candles, company profiles."
    echo -e "      ${DIM}https://finnhub.io/register${RESET}"
    echo
    echo -e "  ${CYAN}[2]${RESET} ${BOLD}Alpha Vantage${RESET} (free API key, 25 requests/day)"
    echo -e "      Daily/weekly/intraday OHLCV, global quotes."
    echo -e "      ${DIM}https://www.alphavantage.co/support/#api-key${RESET}"
    echo
    echo -e "  ${CYAN}[3]${RESET} ${BOLD}Yahoo Finance${RESET} (no key needed, but rate-limits aggressively)"
    echo -e "      Free fallback, no API key required."
    echo
    echo -e "  ${DIM}AEON tries providers in order: Finnhub → Alpha Vantage → Yahoo Finance.${RESET}"
    echo -e "  ${DIM}You can enable multiple providers for maximum reliability.${RESET}"
    echo

    # Finnhub
    echo -ne "  Do you have a Finnhub API key? [y/N] "
    read -r has_finnhub
    if [[ "$has_finnhub" == "y" || "$has_finnhub" == "Y" ]]; then
        echo -ne "  Finnhub API key: "
        read -r finnhub_key
        if [[ -n "$finnhub_key" ]]; then
            _set_env "FINNHUB_API_KEY" "$finnhub_key"
            echo -e "  ${GREEN}ok${RESET} Finnhub configured"
        fi
    else
        echo -e "  ${DIM}Skipped. Get a free key at: https://finnhub.io/register${RESET}"
    fi
    echo

    # Alpha Vantage
    echo -ne "  Do you have an Alpha Vantage API key? [y/N] "
    read -r has_alphavantage
    if [[ "$has_alphavantage" == "y" || "$has_alphavantage" == "Y" ]]; then
        echo -ne "  Alpha Vantage API key: "
        read -r av_key
        if [[ -n "$av_key" ]]; then
            _set_env "ALPHAVANTAGE_API_KEY" "$av_key"
            echo -e "  ${GREEN}ok${RESET} Alpha Vantage configured"
        fi
    else
        echo -e "  ${DIM}Skipped. Get a free key at: https://www.alphavantage.co/support/#api-key${RESET}"
    fi
    echo

    # Yahoo Finance
    echo -ne "  Enable Yahoo Finance as a fallback? (no key needed) [y/N] "
    read -r enable_yahoo
    if [[ "$enable_yahoo" == "y" || "$enable_yahoo" == "Y" ]]; then
        _set_env "AEON_YAHOO_FINANCE_ENABLED" "true"
        echo -e "  ${GREEN}ok${RESET} Yahoo Finance enabled as fallback"
        echo -e "  ${DIM}Note: If you hit rate limits, disable with AEON_YAHOO_FINANCE_ENABLED=false in .env${RESET}"
    else
        _set_env "AEON_YAHOO_FINANCE_ENABLED" "false"
        echo -e "  ${GREEN}ok${RESET} Yahoo Finance disabled"
    fi

    # Summary
    echo
    local stock_count=0
    grep -q "^FINNHUB_API_KEY=.\+" "$ENV_FILE" 2>/dev/null && stock_count=$((stock_count + 1))
    grep -q "^ALPHAVANTAGE_API_KEY=.\+" "$ENV_FILE" 2>/dev/null && stock_count=$((stock_count + 1))
    [[ "$(grep "^AEON_YAHOO_FINANCE_ENABLED=" "$ENV_FILE" 2>/dev/null | cut -d= -f2-)" == "true" ]] && stock_count=$((stock_count + 1))

    if [[ "$stock_count" -eq 0 ]]; then
        echo -e "  ${YELLOW}Note:${RESET} No stock data providers configured. AEON will work in crypto-only mode."
        echo -e "  ${DIM}You can add stock providers later by editing .env${RESET}"
    else
        echo -e "  ${GREEN}ok${RESET} ${stock_count} stock data provider(s) configured"
    fi
}

_configure_budget() {
    echo
    echo -e "  ${CYAN}-- Daily Research Budget --${RESET}"
    echo

    # Show provider-specific guidance
    local provider
    provider="$(grep "^AEON_LLM_PROVIDER=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)"
    [[ -z "$provider" ]] && provider="ollama"

    case "$provider" in
        ollama)
            echo -e "  Ollama is free -- budget only matters if you switch to a cloud"
            echo -e "  provider later. You can leave the default."
            ;;
        bedrock)
            echo -e "  ${BOLD}Rough cost estimates with Bedrock (Claude Sonnet):${RESET}"
            echo -e "    Light research (a few cycles/day):  ~\$0.50/day"
            echo -e "    Active research (continuous):       ~\$1.00-\$2.00/day"
            echo -e "    Heavy research (deep dives):        ~\$3.00-\$5.00/day"
            ;;
        *)
            echo -e "  How much can AEON spend on LLM inference per day?"
            ;;
    esac

    echo -e "  ${DIM}(This caps daily LLM inference spending. Ollama is always free.)${RESET}"
    echo
    echo -ne "  Daily budget in USD [${DIM}1.00${RESET}]: "
    read -r daily_budget
    if [[ -n "$daily_budget" ]]; then
        _set_env "AEON_RESEARCH_BUDGET_DAILY" "$daily_budget"
    fi
    echo -e "  ${GREEN}ok${RESET} Budget set to \$${daily_budget:-1.00}/day"
}

# ---------------------------------------------------------------------------
# Phase 4 -- Verify configuration
# ---------------------------------------------------------------------------
phase4_verify() {
    echo -e "${BOLD}${MAGENTA}Phase 4/5 -- Verify configuration${RESET}"
    echo

    cd "$AEON_HOME"

    # Initialize consciousness database
    echo -e "  ${YELLOW}..${RESET} Initializing consciousness database..."
    "$VENV_PYTHON" -c "
from pathlib import Path
Path('data').mkdir(exist_ok=True)
from aeon.core.consciousness import Consciousness
c = Consciousness(db_path='data/consciousness.db')
c.remember('installation', {'method': 'install_script'}, importance=1.0)
s = c.get_stats()
print(f'  Memories: {s[\"total_memories\"]}  |  DB: {s[\"db_size_kb\"]} KB')
" 2>&1 || yellow "  Database may already exist -- continuing"
    echo -e "  ${GREEN}ok${RESET} Consciousness database ready"

    # Test email if configured
    local smtp_host
    smtp_host="$(grep "^AEON_SMTP_HOST=" "$ENV_FILE" 2>/dev/null | cut -d= -f2- || true)"
    if [[ -n "$smtp_host" ]]; then
        echo -e "  ${GREEN}ok${RESET} Email configured (${smtp_host})"
    else
        echo -e "  ${YELLOW}..${RESET} Email not configured -- updates will only appear in the log"
    fi

    echo
}

# ---------------------------------------------------------------------------
# Phase 5 -- Done
# ---------------------------------------------------------------------------
phase5_done() {
    echo -e "${BOLD}${MAGENTA}Phase 5/5 -- Ready${RESET}"
    echo
    echo -e "  ${GREEN}Installation complete!${RESET}"
    echo
    echo -e "  ${CYAN}================================================================${RESET}"
    echo -e "  ${CYAN}|${RESET}  ${BOLD}Getting Started${RESET}                                             ${CYAN}|${RESET}"
    echo -e "  ${CYAN}================================================================${RESET}"
    echo

    # Check if aeonctl is reachable in PATH
    if command -v aeonctl &>/dev/null; then
        echo -e "  Start the agent interactively:"
        echo -e "    ${BOLD}aeonctl${RESET}"
        echo
        echo -e "  Or start as a background daemon:"
        echo -e "    ${BOLD}aeonctl start -d${RESET}"
        echo
        echo -e "  ${CYAN}Commands:${RESET}"
        echo -e "    aeonctl                         Launch interactive TUI"
        echo -e "    aeonctl status                  Show research status"
        echo -e "    aeonctl steer \"Focus on NVDA\"    Steer the research"
        echo -e "    aeonctl log -f                   Watch the agent think"
        echo -e "    aeonctl history                  See findings and recommendations"
        echo -e "    aeonctl config                   View configuration"
        echo -e "    aeonctl stop                     Stop the agent"
    else
        echo -e "  ${YELLOW}Note:${RESET} Restart your terminal for ${BOLD}aeonctl${RESET} to be available globally."
        echo -e "  Until then, use the full path:"
        echo
        echo -e "    ${BOLD}$AEON_HOME/.venv/bin/aeonctl${RESET}"
        echo
        echo -e "  Or from the project directory:"
        echo -e "    ${BOLD}./aeonctl${RESET}"
        echo
        echo -e "  ${CYAN}Commands:${RESET}"
        echo -e "    aeonctl                         Launch interactive TUI"
        echo -e "    aeonctl status                  Show research status"
        echo -e "    aeonctl steer \"Focus on NVDA\"    Steer the research"
        echo -e "    aeonctl log -f                   Watch the agent think"
        echo -e "    aeonctl history                  See findings and recommendations"
        echo -e "    aeonctl config                   View configuration"
        echo -e "    aeonctl stop                     Stop the agent"
    fi
    echo
    echo -e "  ${DIM}Configuration file: $AEON_HOME/.env${RESET}"
    echo -e "  ${DIM}Data directory:     $AEON_HOME/data/${RESET}"
    echo

    # Ask if they want to start now
    if [[ -t 0 ]]; then
        echo -ne "  Start AEON now? [Y/n] "
        read -r start_now
        if [[ "$start_now" != "n" && "$start_now" != "N" ]]; then
            echo
            cd "$AEON_HOME"
            exec .venv/bin/python -m aeon
        fi
    fi
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    for arg in "$@"; do
        case "$arg" in
            --help|-h)
                echo "Usage: bash install.sh"
                echo
                echo "AEON AI Hedge Fund Manager -- Installation Script"
                echo
                echo "Installs dependencies, configures LLM and email settings,"
                echo "and prepares AEON for first run."
                echo
                echo "Env vars:"
                echo "  AEON_HOME   Project directory (default: auto-detected or ~/.aeon)"
                exit 0
                ;;
        esac
    done

    banner
    phase1_preflight
    phase2_deps
    phase3_configure
    phase4_verify
    phase5_done
}

main "$@"
