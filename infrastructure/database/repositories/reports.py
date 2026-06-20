"""User report repository."""

from __future__ import annotations

from typing import Any

from infrastructure.database.connection import call_json_function
from infrastructure.database.jsonb_helpers import list_from_jsonb, row_from_jsonb


class PostgresReportRepository:
    """Postgres access for user reports."""

    async def create_report(
        self,
        reporter_id: str,
        reported_id: str,
        reason: str,
        description: str | None,
    ) -> dict[str, Any]:
        """Create a user report."""
        try:
            result = await call_json_function(
                "fn_user_reports",
                1,
                {
                    "reporter_id": reporter_id,
                    "reported_id": reported_id,
                    "reason": reason,
                    "description": description,
                },
            )
        except Exception as exc:
            if "cannot_report_self" in str(exc).lower():
                raise ValueError("cannot_report_self") from exc
            raise
        row = row_from_jsonb(result)
        if row is None:
            raise RuntimeError("fn_user_reports mode 1 returned no row")
        return row

    async def list_reports(self, reporter_id: str) -> list[dict[str, Any]]:
        """List reports filed by the given user."""
        result = await call_json_function(
            "fn_user_reports",
            2,
            {"reporter_id": reporter_id},
        )
        return list_from_jsonb(result)
