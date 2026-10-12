import logging
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from app.services.cache import get_revenue_summary
from app.core.auth import authenticate_request as get_current_user
from app.core.database_pool import db_pool
from app.models.auth import AuthenticatedUser

router = APIRouter()
logger = logging.getLogger(__name__)


def require_tenant(user: AuthenticatedUser) -> str:
    if not user.tenant_id:
        raise HTTPException(status_code=403, detail="Tenant context is required")
    return user.tenant_id


@router.get("/dashboard/properties")
async def get_dashboard_properties(current_user: AuthenticatedUser = Depends(get_current_user)):
    tenant_id = require_tenant(current_user)
    try:
        await db_pool.initialize()
        async with db_pool.get_session() as session:
            result = await session.execute(text("""
                SELECT id, name, timezone FROM properties
                WHERE tenant_id = :tenant_id ORDER BY id
            """), {"tenant_id": tenant_id})
            return [dict(row._mapping) for row in result.fetchall()]
    except Exception:
        logger.exception("Failed to read properties")
        raise HTTPException(status_code=503, detail="Property data temporarily unavailable")


@router.get("/dashboard/summary")
async def get_dashboard_summary(
    property_id: str = Query(..., min_length=1),
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=1, le=9998),
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> Dict[str, Any]:
    tenant_id = require_tenant(current_user)
    if month is not None and year is None:
        raise HTTPException(status_code=422, detail="year is required when month is supplied")
    try:
        revenue_data = await get_revenue_summary(property_id, tenant_id, month=month, year=year)
    except LookupError:
        raise HTTPException(status_code=404, detail="Property not found")
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except Exception:
        logger.exception("Failed to calculate revenue")
        raise HTTPException(status_code=503, detail="Revenue data temporarily unavailable")
    return {
        "property_id": revenue_data["property_id"],
        "total_revenue": revenue_data["total"],
        "currency": revenue_data["currency"],
        "reservations_count": revenue_data["count"],
    }
