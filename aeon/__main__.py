"""Entry point for ``python -m aeon``."""

import asyncio

from aeon.app import main

if __name__ == "__main__":
    asyncio.run(main())
