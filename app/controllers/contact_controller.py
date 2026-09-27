from google.cloud.firestore import Client

from app.controllers import crud
from app.dependencies.business_access import BusinessAccess
from app.models.member import members_collection
from app.models.profile import Contact, contacts_collection
from app.schemas.contact import ContactIn
from app.schemas.enums import Permission


def list_contacts(db: Client, business_id: str) -> list[Contact]:
    return crud.list_documents(contacts_collection(db, business_id), Contact)


def create_contact(db: Client, access: BusinessAccess, contact_in: ContactIn) -> Contact:
    access.require(Permission.EDIT_BUSINESS)
    if contact_in.is_primary:
        _clear_primary(db, access.business_id)
    return crud.create_document(
        contacts_collection(db, access.business_id),
        Contact,
        contact_in,
        is_verified=_is_team_member(db, access.business_id, contact_in.user_id),
    )


def update_contact(db: Client, access: BusinessAccess, contact_id: str, contact_in: ContactIn) -> Contact:
    access.require(Permission.EDIT_BUSINESS)
    if contact_in.is_primary:
        _clear_primary(db, access.business_id, except_id=contact_id)
    return crud.update_document(
        contacts_collection(db, access.business_id),
        contact_id,
        Contact,
        contact_in,
        "Contact",
        is_verified=_is_team_member(db, access.business_id, contact_in.user_id),
    )


def delete_contact(db: Client, access: BusinessAccess, contact_id: str) -> None:
    access.require(Permission.EDIT_BUSINESS)
    crud.delete_document(contacts_collection(db, access.business_id), contact_id, "Contact")


def _clear_primary(db: Client, business_id: str, except_id: str | None = None) -> None:
    """Only one contact can be primary, so un-mark the others."""
    for contact in list_contacts(db, business_id):
        if contact.is_primary and contact.id != except_id:
            contacts_collection(db, business_id).document(contact.id).update({"isPrimary": False})


def _is_team_member(db: Client, business_id: str, user_id: str) -> bool:
    """A contact linked to an actual member of the team counts as verified."""
    if not user_id:
        return False
    return members_collection(db, business_id).document(user_id).get().exists
