"""The activity history of a business (its notifications arrive live through the Realtime Database)."""

from fastapi import APIRouter, Depends
from google.cloud.firestore import Client

from app.controllers import activity_controller
from app.core.firebase import get_db
from app.dependencies.business_access import BusinessAccess, get_business_access
from app.models.activity import Activity
from app.schemas.enums import ActivityCategory

router = APIRouter(prefix="/businesses/{business_id}", tags=["Activity"])


@router.get("/activity", response_model=list[Activity])
def list_activity(
    category: ActivityCategory | None = None,
    start: int | None = None,
    end: int | None = None,
    db: Client = Depends(get_db),
    access: BusinessAccess = Depends(get_business_access),
):
    """Newest first. category: PRODUCTS, MESSAGES, or CONNECTIONS (empty = all).
    start / end: milliseconds since 1970 (the browser sends the chosen days' local midnight)."""
    return activity_controller.list_activity(db, access, category, start, end)
