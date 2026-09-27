"""Small helpers for the list / get / create / update / delete steps every resource needs.

Example (from contact_controller.py):
    crud.create_document(contacts_collection(db, business_id), Contact, contact_in)

Reads are cached in Redis (see app/core/cache.py). Writes mark the cache as outdated.
Reads that happen right before a write skip the cache, so an update always starts from
the latest data in Firestore.
"""

from fastapi import HTTPException, status
from google.cloud.firestore import CollectionReference, DocumentReference
from pydantic import BaseModel

from app.core import cache
from app.models.base import FirestoreModel
from app.utils.helpers import current_time_ms


def not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


def bad_request(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def forbidden(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=message)


# ---- Reading (cached) --------------------------------------------------------------------


def list_documents(
    collection: CollectionReference, model_class: type[FirestoreModel], order_by: str = "createdAt"
) -> list:
    """Every document in a collection, oldest first."""
    path = cache.collection_path(collection)
    return cache.cached_models(
        cache.scope_for_path(path),
        f"list:{path}:{order_by}",
        model_class,
        lambda: [model_class.from_snapshot(snapshot) for snapshot in collection.order_by(order_by).stream()],
    )


def get_document(
    collection: CollectionReference, doc_id: str, model_class: type[FirestoreModel], what: str = "Item"
) -> FirestoreModel:
    """One document, or stops the request with 404."""
    doc_ref = collection.document(doc_id)
    item = cache.cached_model(
        cache.scope_for_path(doc_ref.path), f"doc:{doc_ref.path}", model_class, lambda: _read(doc_ref, model_class)
    )
    if item is None:
        raise not_found(what)
    return item


def find_document(
    collection: CollectionReference, doc_id: str, model_class: type[FirestoreModel]
) -> FirestoreModel | None:
    """Like get_document, but returns None instead of stopping the request when it does not exist."""
    doc_ref = collection.document(doc_id)
    return cache.cached_model(
        cache.scope_for_path(doc_ref.path), f"doc:{doc_ref.path}", model_class, lambda: _read(doc_ref, model_class)
    )


def get_single_document(doc_ref: DocumentReference, model_class: type[FirestoreModel]) -> FirestoreModel:
    """For details that exist once per business (like legal info). Returns empty defaults if never saved."""
    item = cache.cached_model(
        cache.scope_for_path(doc_ref.path), f"doc:{doc_ref.path}", model_class, lambda: _read(doc_ref, model_class)
    )
    return item if item is not None else model_class(id=doc_ref.id)


def _read(doc_ref: DocumentReference, model_class: type[FirestoreModel]) -> FirestoreModel | None:
    """Reads one document straight from Firestore (no cache). None when it does not exist."""
    snapshot = doc_ref.get()
    return model_class.from_snapshot(snapshot) if snapshot.exists else None


# ---- Writing (marks the cache as outdated) -----------------------------------------------


def create_document(
    collection: CollectionReference, model_class: type[FirestoreModel], data: BaseModel, **extra_fields
) -> FirestoreModel:
    """Saves a new document with a random id. `extra_fields` add or override fields (e.g. system fields)."""
    doc_ref = collection.document()
    now = current_time_ms()
    item = model_class(**{**data.model_dump(), **extra_fields, "id": doc_ref.id, "created_at": now, "updated_at": now})
    doc_ref.set(item.to_firestore())
    cache.bump(cache.scope_for_path(doc_ref.path))
    return item


def update_document(
    collection: CollectionReference, doc_id: str, model_class: type[FirestoreModel], data: BaseModel, what: str = "Item",
    **extra_fields,
) -> FirestoreModel:
    """Replaces the form fields of a document. System fields that are not in `data` are kept."""
    doc_ref = collection.document(doc_id)
    existing = _read(doc_ref, model_class)
    if existing is None:
        raise not_found(what)
    item = model_class(**{**existing.model_dump(), **data.model_dump(), **extra_fields, "updated_at": current_time_ms()})
    doc_ref.set(item.to_firestore())
    cache.bump(cache.scope_for_path(doc_ref.path))
    return item


def delete_document(collection: CollectionReference, doc_id: str, what: str = "Item") -> None:
    doc_ref = collection.document(doc_id)
    if not doc_ref.get().exists:
        raise not_found(what)
    doc_ref.delete()
    cache.bump(cache.scope_for_path(doc_ref.path))


def save_single_document(
    doc_ref: DocumentReference, model_class: type[FirestoreModel], data: BaseModel, **extra_fields
) -> FirestoreModel:
    existing = _read(doc_ref, model_class) or model_class(id=doc_ref.id)
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
    cache.bump(cache.scope_for_path(doc_ref.path))
    return item
