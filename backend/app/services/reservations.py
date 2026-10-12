from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import text
from app.core.database_pool import db_pool


def revenue_bounds(year: int, month: Optional[int], property_timezone: str):
    """Property-local check-in reporting period as a half-open UTC range.

    Construct both boundaries separately to respect DST offset changes.
    """
    if not 1 <= year <= 9998 or (month is not None and not 1 <= month <= 12):
        raise ValueError("Invalid reporting period")
    zone = ZoneInfo(property_timezone)
    start = datetime(year, month or 1, 1, tzinfo=zone)
    if month is None or month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=zone)
    else:
        end = datetime(year, month + 1, 1, tzinfo=zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


async def calculate_monthly_revenue(
    property_id: str, month: int, year: int, tenant_id: str, db_session=None
) -> Decimal:
    result = await calculate_total_revenue(
        property_id, tenant_id, month=month, year=year, db_session=db_session
    )
    return Decimal(result["total"])


async def _calculate(session, property_id, tenant_id, month, year):
    params = {"property_id": property_id, "tenant_id": tenant_id}
    property_result = await session.execute(text("""
        SELECT timezone FROM properties
        WHERE id = :property_id AND tenant_id = :tenant_id
    """), params)
    property_row = property_result.fetchone()
    if property_row is None:
        raise LookupError("Property not found")

    period_filter = ""
    if year is not None:
        params["start_date"], params["end_date"] = revenue_bounds(
            year, month, property_row.timezone
        )
        period_filter = "AND check_in_date >= :start_date AND check_in_date < :end_date"
    elif month is not None:
        raise ValueError("year is required when month is supplied")

    result = await session.execute(text(f"""
        SELECT currency, SUM(total_amount) AS total_revenue,
               COUNT(*) AS reservation_count
        FROM reservations
        WHERE property_id = :property_id AND tenant_id = :tenant_id
        {period_filter}
        GROUP BY currency
    """), params)
    rows = result.fetchall()
    # No FX source is supplied. Never add unlike currencies into a fake USD total.
    if len(rows) > 1:
        raise ValueError("Multiple currencies cannot be combined without exchange rates")
    row = rows[0] if rows else None
    total = Decimal(str(row.total_revenue)) if row else Decimal("0")
    # Sum NUMERIC sub-cent values first; round once at the reporting boundary.
    total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "total": format(total, ".2f"),
        "currency": row.currency if row else "USD",
        "count": row.reservation_count if row else 0,
    }


async def calculate_total_revenue(
    property_id: str, tenant_id: str, month: Optional[int] = None,
    year: Optional[int] = None, db_session=None
) -> Dict[str, Any]:
    """Read real tenant-scoped revenue; never substitute mocks on DB failure."""
    if not tenant_id:
        raise ValueError("Tenant is required")
    if db_session is not None:
        return await _calculate(db_session, property_id, tenant_id, month, year)
    await db_pool.initialize()
    async with db_pool.get_session() as session:
        return await _calculate(session, property_id, tenant_id, month, year)

