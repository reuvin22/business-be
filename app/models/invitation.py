"""Invitations to join a business's team (as a member, or as a seller with an account they already have).

Firestore location:  invitations/{businessId}_{userId}   (top-level, so a user can find their own)

Nobody is added to a team without saying yes: the invitation becomes a member when the person accepts it.
"""

from google.cloud.firestore import Client, CollectionReference

from app.models.base import FirestoreModel
from app.schemas.enums import MemberRole, Permission


class Invitation(FirestoreModel):
    # Encrypted in Firestore: personal contact details (see app/core/crypto.py)
    encrypted_fields = ("email",)

    business_id: str
    business_name: str
    business_logo: str = ""
    uid: str  # the person invited
    email: str = ""
    display_name: str = ""
    role: MemberRole
    permissions: list[Permission] = []
    location_id: str | None = None  # sellers: the store they will sell from
    invited_by_name: str = ""


def invitations_collection(db: Client) -> CollectionReference:
    return db.collection("invitations")


def invitation_id(business_id: str, uid: str) -> str:
    return f"{business_id}_{uid}"
