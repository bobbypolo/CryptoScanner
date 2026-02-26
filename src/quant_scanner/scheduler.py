"""Background scan scheduler for the Crypto Quant Scanner dashboard.

Runs run_screen() on a configurable interval, stores results in ScanStore,
and never crashes the server. Uses asyncio.Event for manual trigger support.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from quant_scanner.scan_store import ScanStore

logger = logging.getLogger(__name__)


class ScanScheduler:
    """Async background scheduler that periodically runs the screening pipeline.

    Parameters
    ----------
    store : ScanStore
        In-memory store for scan results and status.
    interval_seconds : int
        Seconds between scan cycles (default 300 = 5 minutes).
    scan_kwargs : dict | None
        Keyword arguments forwarded to ``run_screen()``.
        Defaults to ``{'use_cache': True}`` if not provided.
    ws_manager : ConnectionManager | None
        Optional WebSocket manager for broadcasting scan results.
    """

    def __init__(
        self,
        store: ScanStore,
        interval_seconds: int = 300,
        scan_kwargs: dict | None = None,
        ws_manager: object | None = None,
    ) -> None:
        self.store = store
        self.interval_seconds = interval_seconds
        self.scan_kwargs: dict = scan_kwargs if scan_kwargs is not None else {"use_cache": True}
        self.ws_manager = ws_manager

        self._scanning: bool = False
        self._task: asyncio.Task | None = None
        self._trigger_event: asyncio.Event = asyncio.Event()
        self._last_trigger_time: float = 0

    async def start(self) -> None:
        """Launch the background scan loop.

        Idempotent: calling start() twice does not create two loops.
        """
        if self._task is not None and not self._task.done():
            logger.warning("Scheduler already running — ignoring duplicate start()")
            return
        self._task = asyncio.create_task(self._loop())
        logger.info("Scheduler started (interval=%ds)", self.interval_seconds)

    async def stop(self) -> None:
        """Cancel the background scan loop and wait for cleanup.

        Uses a 30-second timeout. If the task doesn't finish in time,
        a warning is logged but shutdown continues (no hang).
        """
        if self._task is None:
            return
        self._task.cancel()
        try:
            await asyncio.wait_for(self._task, timeout=30)
        except asyncio.TimeoutError:
            logger.warning("Scheduler task did not finish within 30s timeout")
        except asyncio.CancelledError:
            pass  # expected
        self._task = None
        logger.info("Scheduler stopped")

    async def trigger_now(self) -> None:
        """Manually trigger an immediate scan.

        No-ops if a scan is already running or if called within 10 seconds
        of the last trigger (cooldown to prevent abuse).
        """
        if self._scanning:
            return
        if time.monotonic() - self._last_trigger_time < 10:
            return
        self._last_trigger_time = time.monotonic()
        self._trigger_event.set()

    async def _loop(self) -> None:
        """Infinite scan loop with drift-corrected sleep."""
        try:
            while True:
                scan_start = time.monotonic()
                await self._run_one_scan()

                remaining = max(0, self.interval_seconds - (time.monotonic() - scan_start))

                # Compute next scan time and store it
                next_scan_at = datetime.now(timezone.utc) + timedelta(seconds=remaining)
                self.store.set_next_scan_at(next_scan_at)

                # Wait for either the interval to elapse or a manual trigger
                sleep_future = asyncio.ensure_future(asyncio.sleep(remaining))
                event_future = asyncio.ensure_future(self._trigger_event.wait())

                done, pending = await asyncio.wait(
                    {sleep_future, event_future},
                    return_when=asyncio.FIRST_COMPLETED,
                )

                # Cancel whichever didn't finish
                for fut in pending:
                    fut.cancel()
                    try:
                        await fut
                    except asyncio.CancelledError:
                        pass

                # Clear the event so it can be re-used
                self._trigger_event.clear()

        except asyncio.CancelledError:
            logger.info("Scheduler loop cancelled")
            raise

    async def _run_one_scan(self) -> None:
        """Execute a single scan cycle.

        Catches ALL exceptions so the loop never crashes.
        Imports run_screen lazily to avoid circular imports.
        """
        self._scanning = True
        self.store.set_scanning()
        scan_start = time.monotonic()
        logger.info("Scan started")

        try:
            # Lazy import to prevent circular imports and ensure
            # --dry-run works without importing the server
            from quant_scanner.screener_engine import run_screen

            result = await run_screen(**self.scan_kwargs)

            await self.store.update(result)
            self.store.clear_error()

            duration = time.monotonic() - scan_start
            logger.info(
                "Scan complete: %d coins in %.1fs",
                len(result),
                duration,
            )

            # Broadcast via WebSocket if manager is available
            if self.ws_manager is not None:
                await self.ws_manager.broadcast(
                    {
                        "type": "scan_complete",
                        "coin_count": len(result),
                        "scanned_at": datetime.now(timezone.utc).isoformat(),
                    }
                )

        except Exception as e:
            self.store.set_error(str(e))
            logger.exception("Scan failed: %s", e)
        finally:
            self._scanning = False
