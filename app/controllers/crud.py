"""Small helpers for the list / get / create / update / delete steps every resource needs.

Example (from contact_controller.py):
    crud.create_document(contacts_collection(db, business_id), Contact, contact_in)
"""

from fastapi import HTTPException, status
from google.cloud.firestore import CollectionReference, DocumentReference
from pydantic import BaseModel

from app.models.base import FirestoreModel
from app.utils.helpers import current_time_ms


def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


def bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def forbidden(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


def list_documents(
    collection: CollectionReference, model_class: type[FirestoreModel], order_by: str = "createdAt"
) -> list:
    """Every document in a collection, oldest first."""
    return [model_class.from_snapshot(snapshot) for snapshot in collection.order_by(order_by).stream()]


def get_document(
    collection: CollectionReference, doc_id: str, model_class: type[FirestoreModel], what: str = "Item"
) -> FirestoreModel:
    """One document, or stops the request with 404."""
    snapshot = collection.document(doc_id).get()
    if not snapshot.exists:
        raise not_found(what)
    return model_class.from_snapshot(snapshot)


def create_document(
    collection: CollectionReference, model_class: type[FirestoreModel], data: BaseModel, **extra_fields
) -> FirestoreModel:
    """Saves a new document with a random id. `extra_fields` add or override fields (e.g. system fields)."""
    doc_ref = collection.document()
    now = current_time_ms()
    item = model_class(**{**data.model_dump(), **extra_fields, "id": doc_ref.id, "created_at": now, "updated_at": now})
    doc_ref.set(item.to_firestore())
    return item


def update_document(
    collection: CollectionReference, doc_id: str, model_class: type[FirestoreModel], data: BaseModel, what: str = "Item",
    **extra_fields,
) -> FirestoreModel:
    """Replaces the form fields of a document. System fields that are not in `data` are kept."""
    existing = get_document(collection, doc_id, model_class, what)
    item = model_class(**{**existing.model_dump(), **data.model_dump(), **extra_fields, "updated_at": current_time_ms()})
    collection.document(doc_id).set(item.to_firestore())
    return item


def delete_document(collection: CollectionReference, doc_id: str, what: str = "Item") -> None:
    if not collection.document(doc_id).get().exists:
        raise not_found(what)
    collection.document(doc_id).delete()


def get_single_document(doc_ref: DocumentReference, model_class: type[FirestoreModel]) -> FirestoreModel:
    """For details that exist once per business (like legal info). Returns empty defaults if never saved."""
    snapshot = doc_ref.get()
    if snapshot.exists:
        return model_class.from_snapshot(snapshot)
    return model_class(id=doc_ref.id)


def save_single_document(
    doc_ref: DocumentReference, model_class: type[FirestoreModel], data: BaseModel, **extra_fields
) -> FirestoreModel:
    existing = get_single_document(doc_ref, model_class)
    now = current_time_ms()
    item = model_class(
        **{
            **existing.model_dump(),
            **data.model_dump(),
            **extra_fields,
            "id": doc_ref.id,
            "created_at": existing.created_at or now,
            "updated_at": now,
        }
    )
    doc_ref.set(item.to_firestore())
    return item
