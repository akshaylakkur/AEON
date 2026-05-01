"""Entry point for ``python -m aeon.orchestrator``."""

import sys

from aeon.orchestrator.manager import main

if __name__ == "__main__":
    sys.exit(main())
