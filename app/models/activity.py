"""The activity history of a business: product changes, messages, and connections.

Firestore location:  businesses/{businessId}/activity/{activityId}
Each entry is also pushed live to the Realtime Database (live/{businessId}/activity), which drives
the notification bell and refreshes open pages (see app/controllers/activity_controller.py).
"""

from google.cloud.firestore import Client, CollectionReference

from app.models.base import FirestoreModel
from app.models.business import business_subcollection
from app.schemas.enums import ActivityCategory


class Activity(FirestoreModel):
    category: ActivityCategory  # what the filters group by
    action: str  # e.g. "product.created", "connection.accepted", "message.received"
    title: str  # what happened, from this business's point of view
    detail: str = ""
    link: str = ""  # the page to open, relative to the business, e.g. "/products/abc"
    actor_uid: str = ""  # who did it ("" when another business did it)
    actor_name: str = ""


def activity_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "activity")
