"""ScanStore -- Coroutine-safe in-memory data store for scan results.

Coroutine-safe (asyncio.Lock), NOT thread-safe. All access must happen
on a single asyncio event loop.  If uvicorn is ever run with
``--workers > 1``, each worker gets its own store instance.
Do NOT use ``run_in_executor()`` to access the store from a thread.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pandas as pd


class ScanStore:
    """Coroutine-safe (asyncio.Lock), NOT thread-safe. All access on single event loop."""

    def __init__(self, max_history: int = 288) -> None:
        """Initialise the store.

        Parameters
        ----------
        max_history:
            Maximum number of snapshot summaries to keep (default 288 =
            24 h at 5-min intervals).
        """
        self._max_history = max_history
        self._latest: pd.DataFrame | None = None
        self._history: list[dict[str, Any]] = []
        self._scan_count: int = 0
        self._status: str = "idle"
        self._error: str | None = None
        self._last_scan_at: str | None = None
        self._next_scan_at: str | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def update(self, df: pd.DataFrame) -> None:
        """Store a new scan result.

        Acquires the asyncio lock, stores a *copy* of *df* (to prevent
        caller mutation), records a UTC timestamp, appends a snapshot
        summary to history, trims history to ``max_history``, increments
        scan count, and sets ``last_scan_at``.
        """
        async with self._lock:
            self._latest = df.copy()
            now = datetime.now(timezone.utc)
            self._last_scan_at = now.isoformat()

            # Build snapshot summary
            top_beta_symbol: str | None = None
            if not df.empty and "beta" in df.columns:
                idx = df["beta"].idxmax()
                top_beta_symbol = df.loc[idx, "symbol"] if "symbol" in df.columns else None

            snapshot: dict[str, Any] = {
                "timestamp": now.isoformat(),
                "coin_count": len(df),
                "top_beta_symbol": top_beta_symbol,
            }
            self._history.append(snapshot)

            # Trim to max_history
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history :]

            self._scan_count += 1
            self._status = "idle"

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_latest(self) -> pd.DataFrame | None:
        """Return a *copy* of the most recent scan DataFrame, or ``None``.

        Returns a copy to prevent route handlers from mutating stored
        data.
        """
        if self._latest is not None:
            return self._latest.copy()
        return None

    def get_latest_as_records(self) -> list[dict[str, Any]]:
        """Return latest scan results as a list of dicts, NaN-safe.

        Converts all NaN/None values to ``None`` so the output is safe
        for ``json.dumps()`` (NaN is **not** valid JSON per RFC 8259).
        This is the ONLY method API routes should use for JSON
        responses.
        """
        if self._latest is None:
            return []
        # Must cast to object dtype first -- in float64 columns pandas
        # silently coerces None back to NaN.  Object dtype preserves None.
        safe = self._latest.astype(object).where(self._latest.notna(), None)
        return safe.to_dict(orient="records")

    def get_history(self, limit: int = 24) -> list[dict[str, Any]]:
        """Return the last *limit* snapshot summaries."""
        return self._history[-limit:]

    def get_status(self) -> dict[str, Any]:
        """Return current scan metadata.

        Note: ``uptime_seconds`` is NOT included here -- it belongs
        only in ``/api/health``, computed from ``app.state.start_time``
        using ``time.monotonic()``.
        """
        return {
            "last_scan_at": self._last_scan_at,
            "next_scan_at": self._next_scan_at,
            "scan_count": self._scan_count,
            "coin_count": len(self._latest) if self._latest is not None else 0,
            "status": self._status,
            "error": self._error,
        }

    # ------------------------------------------------------------------
    # Status mutators
    # ------------------------------------------------------------------

    def set_error(self, error: str) -> None:
        """Set status to ``'error'`` with the given message."""
        self._status = "error"
        self._error = error

    def clear_error(self) -> None:
        """Clear error state, resetting to ``'idle'``."""
        self._status = "idle"
        self._error = None

    def set_scanning(self) -> None:
        """Set status to ``'scanning'``."""
        self._status = "scanning"

    def set_next_scan_at(self, dt: datetime) -> None:
        """Update the ``next_scan_at`` field with an ISO-formatted timestamp."""
        self._next_scan_at = dt.isoformat()
