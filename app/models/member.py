from google.cloud.firestore import Client, CollectionReference

from app.models.base import FirestoreModel
from app.models.business import business_subcollection
from app.schemas.enums import MemberRole, MemberStatus, Permission

# Firestore location:  businesses/{businessId}/members/{userId}
# The document id is the member's Firebase user id, so there is at most one per person.


class Member(FirestoreModel):
    """A user who belongs to a business (section 25). A user can be a member of several businesses."""

    # Encrypted in Firestore: personal contact details (see app/core/crypto.py)
    encrypted_fields = ("email",)

    email: str = ""
    display_name: str = ""
    role: MemberRole
    permissions: list[Permission] = []
    status: MemberStatus = MemberStatus.ACTIVE
    joined_at: int = 0
    # Sellers only: the store (location) they sell from. None = any location.
    location_id: str | None = None
    # Sellers only: True when this business created the login, so it may set its password. An account the
    # person already had (and joined by accepting an invitation) is theirs alone: nobody else may change it.
    account_managed: bool = False

    @property
    def user_id(self) -> str:
        return self.id


def members_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "members")
