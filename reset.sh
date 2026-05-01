#!/bin/bash
# Complete reset script for AEON

set -euo pipefail

echo "AEON Complete Reset"
echo "======================================"
echo ""
echo "This will:"
echo "  - Delete .env configuration"
echo "  - Delete .venv virtual environment"
echo "  - Clear data/ directory"
echo "  - Clear any generated databases"
echo ""
read -p "Continue? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Reset cancelled."
    exit 0
fi

echo ""
echo "Resetting AEON..."
echo ""

# 1. Remove .env
if [[ -f .env ]]; then
    echo "Removing .env"
    rm -f .env
fi

# 2. Remove virtual environment
if [[ -d .venv ]]; then
    echo "Removing .venv/"
    rm -rf .venv
fi

# 3. Clear data directory
if [[ -d data ]]; then
    echo "Clearing data/"
    rm -rf data/*
fi

# 4. Clear any pycache and build artifacts
echo "Clearing __pycache__ and build artifacts"
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
find . -type d -name .eggs -exec rm -rf {} + 2>/dev/null || true
find . -type d -name *.egg-info -exec rm -rf {} + 2>/dev/null || true

echo ""
echo "Reset complete!"
echo ""
echo "Next steps:"
echo "  1. Run: bash install.sh"
echo "  2. Follow the installation wizard"
echo ""
