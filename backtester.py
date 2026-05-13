"""
Root entry point for Talosly's historical hack backtester.

Usage:
    python backtester.py
    python backtester.py --preset all
    python backtester.py --preset euler
    python backtester.py --preset venus

The implementation lives in backend.tests.backtest_hacks so the root script and
test module stay in sync.
"""

from __future__ import annotations

import asyncio

from backend.tests.backtest_hacks import main


if __name__ == "__main__":
    asyncio.run(main())
