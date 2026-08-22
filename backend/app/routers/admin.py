"""Owner-only console: who has been asking, and what."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..deps import require_owner
from ..models.schemas import AnalyticsResponse, Lead
from ..services import analytics

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_owner)])


@router.get("/analytics", response_model=AnalyticsResponse)
async def get_analytics(limit: int = 40) -> AnalyticsResponse:
    return analytics.summary(min(max(limit, 1), 200))


@router.delete("/analytics", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def clear_analytics() -> Response:
    """Clear the question and match logs.

    Leaves saved leads intact - they are contacts, not activity, and a click
    labelled "clear log" should never destroy someone's inbound recruiters.
    """
    analytics.clear_activity()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/leads", response_model=list[Lead])
async def get_leads(limit: int = 100) -> list[Lead]:
    return analytics.list_leads(min(max(limit, 1), 500))


@router.delete("/leads", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def clear_leads() -> Response:
    analytics.clear_leads()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/leads/{lead_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
async def delete_lead(lead_id: int) -> Response:
    if not analytics.delete_lead(lead_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such lead.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/verify")
async def verify_token() -> dict:
    """Cheap endpoint the frontend uses to check a token before showing the dashboard."""
    return {"ok": True}
