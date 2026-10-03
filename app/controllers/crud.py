"""Small helpers for the list / get / create / update / delete steps every resource needs.

Example (from contact_controller.py):
    crud.create_document(contacts_collection(db, business_id), Contact, contact_in)

Reads are cached in Redis (see app/core/cache.py). Writes mark the cache as outdated.
Reads that happen right before a write skip the cache, so an update always starts from
the latest data in Firestore.
"""

import logging

from fastapi import HTTPException, status
from google.api_core.exceptions import FailedPrecondition
from google.cloud.firestore import CollectionReference, DocumentReference, DocumentSnapshot, Query
from pydantic import BaseModel

from app.core import cache, storage
from app.models.base import FirestoreModel
from app.utils.helpers import current_time_ms


logger = logging.getLogger(__name__)


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
        cache.scope_for_path(doc_ref.path), f"doc:{doc_ref.path}", model_class, lambda: read_fresh(doc_ref, model_class)
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
        cache.scope_for_path(doc_ref.path), f"doc:{doc_ref.path}", model_class, lambda: read_fresh(doc_ref, model_class)
    )


def get_single_document(doc_ref: DocumentReference, model_class: type[FirestoreModel]) -> FirestoreModel:
    """For details that exist once per business (like legal info). Returns empty defaults if never saved."""
    item = cache.cached_model(
        cache.scope_for_path(doc_ref.path), f"doc:{doc_ref.path}", model_class, lambda: read_fresh(doc_ref, model_class)
    )
    return item if item is not None else model_class(id=doc_ref.id)


def read_fresh(doc_ref: DocumentReference, model_class: type[FirestoreModel]) -> FirestoreModel | None:
    """Reads one document straight from Firestore (no cache), e.g. right before changing it.
    None when it does not exist."""
    snapshot = doc_ref.get()
    return model_class.from_snapshot(snapshot) if snapshot.exists else None


def stream_indexed(query: Query, fallback: Query) -> list[DocumentSnapshot]:
    """Runs a query that needs a composite index (see firestore.indexes.json).

    Until that index is deployed and built, Firestore refuses the query. Then `fallback` (a simpler
    query that needs no composite index; the caller still sorts/filters in Python) runs instead,
    so the page keeps working, and the server log says to deploy the indexes."""
    try:
        return list(query.stream())
    except FailedPrecondition as error:
        logger.warning("Firestore index missing, using a slower query. Deploy firestore.indexes.json. %s", error)
        return list(fallback.stream())


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
    existing = read_fresh(doc_ref, model_class)
    if existing is None:
        raise not_found(what)
    item = model_class(**{**existing.model_dump(), **data.model_dump(), **extra_fields, "updated_at": current_time_ms()})
    doc_ref.set(item.to_firestore())
    cache.bump(cache.scope_for_path(doc_ref.path))
    storage.delete_removed(existing.file_urls(), item.file_urls())  # e.g. a replaced photo
    return item


def delete_document(
    collection: CollectionReference, doc_id: str, what: str = "Item", model_class: type[FirestoreModel] | None = None
) -> None:
    """Deletes the document. Given the model class, the files it used are deleted from storage too."""
    doc_ref = collection.document(doc_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        raise not_found(what)
    doc_ref.delete()
    cache.bump(cache.scope_for_path(doc_ref.path))
    if model_class is not None:
        storage.delete_removed(model_class.from_snapshot(snapshot).file_urls(), [])


def save_single_document(
    doc_ref: DocumentReference, model_class: type[FirestoreModel], data: BaseModel, **extra_fields
) -> FirestoreModel:
    existing = read_fresh(doc_ref, model_class) or model_class(id=doc_ref.id)
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
    storage.delete_removed(existing.file_urls(), item.file_urls())
    return item
