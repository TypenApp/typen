"""
BYOK Token Usage and Cost Visibility Tracker.
Records token consumption and estimated USD cost in local SQLite without ever
storing the user's prompt text or response content.
"""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

# Indicative per-1M-token pricing table (USD) for cost estimation
MODEL_PRICING_PER_1M_USD: Final[dict[str, tuple[Decimal, Decimal]]] = {
    "gpt-4o-mini": (Decimal("0.15"), Decimal("0.60")),
    "gpt-4o": (Decimal("2.50"), Decimal("10.00")),
    "claude-3-5-haiku-latest": (Decimal("0.80"), Decimal("4.00")),
    "claude-3-7-sonnet-latest": (Decimal("3.00"), Decimal("15.00")),
    "gemini-2.5-flash": (Decimal("0.15"), Decimal("0.60")),
}


@dataclass(frozen=True, slots=True)
class ProviderUsageSummary:
    """Aggregated token and estimated cost metrics."""

    total_requests: int
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: Decimal


class UsageTracker:
    """
    Local SQLite ledger for BYOK API usage and cost visibility.
    Zero prompt/document content is ever written to this database.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_usage_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc REAL NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    prompt_tokens INTEGER NOT NULL,
                    completion_tokens INTEGER NOT NULL,
                    cost_usd_str TEXT NOT NULL
                );
                """
            )

    @staticmethod
    def estimate_cost_usd(
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> Decimal:
        in_rate, out_rate = MODEL_PRICING_PER_1M_USD.get(
            model, (Decimal("1.00"), Decimal("3.00"))
        )
        cost = (
            Decimal(prompt_tokens) * in_rate + Decimal(completion_tokens) * out_rate
        ) / Decimal("1000000")
        return cost.quantize(Decimal("0.000001"))

    def record_usage(
        self,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        timestamp_utc: float | None = None,
    ) -> Decimal:
        ts = timestamp_utc if timestamp_utc is not None else time.time()
        cost = self.estimate_cost_usd(model, prompt_tokens, completion_tokens)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ai_usage_events
                (timestamp_utc, provider, model, prompt_tokens, completion_tokens, cost_usd_str)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (ts, provider.lower(), model, prompt_tokens, completion_tokens, str(cost)),
            )
        return cost

    def get_summary_since(
        self,
        since_timestamp_utc: float = 0.0,
        provider: str | None = None,
    ) -> ProviderUsageSummary:
        query = (
            "SELECT COUNT(*), COALESCE(SUM(prompt_tokens), 0), "
            "COALESCE(SUM(completion_tokens), 0) "
            "FROM ai_usage_events WHERE timestamp_utc >= ?"
        )
        params: list[object] = [since_timestamp_utc]
        if provider:
            query += " AND provider = ?"
            params.append(provider.lower())

        cost_query = "SELECT cost_usd_str FROM ai_usage_events WHERE timestamp_utc >= ?"
        if provider:
            cost_query += " AND provider = ?"

        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
            cost_rows = conn.execute(cost_query, params).fetchall()

        total_cost = sum((Decimal(r[0]) for r in cost_rows), Decimal("0.000000"))
        return ProviderUsageSummary(
            total_requests=int(row[0]) if row else 0,
            prompt_tokens=int(row[1]) if row else 0,
            completion_tokens=int(row[2]) if row else 0,
            estimated_cost_usd=total_cost,
        )
