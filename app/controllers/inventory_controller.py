"""Stock per product (or variant) per location, and the stock history.

Every change to a quantity on hand also saves a StockMovement, in the same batch or
transaction as the change itself, so the history always matches the stock.
"""

from dataclasses import dataclass

from google.cloud import firestore
from google.cloud.firestore import Client, DocumentReference, FieldFilter, Transaction

from app.controllers import crud
from app.controllers.crud import bad_request, not_found
from app.controllers.product_controller import get_product, get_variant
from app.core import cache
from app.dependencies.business_access import BusinessAccess
from app.models.inventory import (
    InventoryItem,
    StockMovement,
    inventory_collection,
    inventory_document,
    stock_movements_collection,
)
from app.models.product import Product, Variant, products_collection, variants_collection
from app.models.profile import Location, locations_collection
from app.schemas.enums import Permission, StockMovementType, StockStatus
from app.schemas.inventory import InventoryAdjustIn, InventoryIn, InventoryUpdateIn
from app.schemas.user import CurrentUser
from app.utils.helpers import current_time_ms


def calculate_stock(item: InventoryItem) -> InventoryItem:
    """Works out the available quantity and the stock status from quantity, reserved, and reorder level."""
    item.available_quantity = item.quantity - item.reserved_quantity
    if item.available_quantity <= 0:
        item.stock_status = StockStatus.OUT_OF_STOCK
    elif item.reorder_level is not None and item.available_quantity <= item.reorder_level:
        item.stock_status = StockStatus.LOW_STOCK
    else:
        item.stock_status = StockStatus.IN_STOCK
    return item


def list_inventory(db: Client, business_id: str) -> list[InventoryItem]:
    return crud.list_documents(inventory_collection(db, business_id), InventoryItem)


# ---- Stock history -----------------------------------------------------------------------


@dataclass
class StockNames:
    """Readable names saved on each history line."""

    product_name: str
    variant_name: str
    location_name: str


def stock_names(db: Client, business_id: str, product_id: str, variant_id: str | None, location_id: str) -> StockNames:
    product = crud.find_document(products_collection(db, business_id), product_id, Product)
    variant = crud.find_document(variants_collection(db, business_id, product_id), variant_id, Variant) if variant_id else None
    return StockNames(
        product_name=product.product_name if product else "Deleted product",
        variant_name=variant.variant_name if variant else "",
        location_name=location_name(db, business_id, location_id),
    )


def location_name(db: Client, business_id: str, location_id: str) -> str:
    location = crud.find_document(locations_collection(db, business_id), location_id, Location)
    return location.location_name if location else "Deleted location"


def new_movement(
    db: Client,
    business_id: str,
    stock: InventoryItem,
    names: StockNames,
    movement_type: StockMovementType,
    change: float,
    by: CurrentUser | None,
    note: str = "",
    reference_id: str = "",
    reference_label: str = "",
) -> tuple[DocumentReference, StockMovement]:
    """A history line for a change to `stock` (call AFTER changing stock.quantity). Save it with
    the same batch or transaction as the stock: `writer.set(ref, movement.to_firestore())`."""
    ref = stock_movements_collection(db, business_id).document()
    now = current_time_ms()
    movement = StockMovement(
        id=ref.id,
        product_id=stock.product_id,
        variant_id=stock.variant_id,
        location_id=stock.location_id,
        **vars(names),
        movement_type=movement_type,
        change=change,
        quantity_after=stock.quantity,
        note=note,
        reference_id=reference_id,
        reference_label=reference_label,
        by_uid=by.uid if by else "",
        by_name=(by.name or by.email or "") if by else "",
        created_at=now,
        updated_at=now,
    )
    return ref, movement


def list_movements(
    db: Client, business_id: str, product_id: str | None = None, location_id: str | None = None, limit: int = 300
) -> list[StockMovement]:
    """The stock history, newest first. Filter by product and/or location."""

    def read() -> list[StockMovement]:
        collection = stock_movements_collection(db, business_id)
        if product_id:
            query = collection.where(filter=FieldFilter("productId", "==", product_id))
        elif location_id:
            query = collection.where(filter=FieldFilter("locationId", "==", location_id))
        else:
            query = collection.order_by("createdAt", direction=firestore.Query.DESCENDING).limit(limit)
        return [StockMovement.from_snapshot(snapshot) for snapshot in query.stream()]

    movements = cache.cached_models(
        cache.business_scope(business_id), f"movements:{product_id}:{location_id}:{limit}", StockMovement, read
    )
    if location_id:
        movements = [m for m in movements if m.location_id == location_id]
    return sorted(movements, key=lambda m: m.created_at, reverse=True)[:limit]


# ---- Changing stock ----------------------------------------------------------------------


def create_inventory(db: Client, access: BusinessAccess, inventory_in: InventoryIn) -> InventoryItem:
    access.require(Permission.MANAGE_INVENTORY)
    get_product(db, access.business_id, inventory_in.product_id)
    if inventory_in.variant_id:
        get_variant(db, access.business_id, inventory_in.product_id, inventory_in.variant_id)
    if not locations_collection(db, access.business_id).document(inventory_in.location_id).get().exists:
        raise not_found("Location")

    doc_ref = inventory_document(
        db, access.business_id, inventory_in.product_id, inventory_in.variant_id, inventory_in.location_id
    )
    if doc_ref.get().exists:
        raise bad_request("This product already has stock at this location. Edit that record instead.")

    now = current_time_ms()
    item = calculate_stock(InventoryItem(**inventory_in.model_dump(), id=doc_ref.id, created_at=now, updated_at=now))
    names = stock_names(db, access.business_id, item.product_id, item.variant_id, item.location_id)
    movement_ref, movement = new_movement(
        db, access.business_id, item, names, StockMovementType.STOCK_ADDED, item.quantity, access.user
    )

    batch = db.batch()
    batch.set(doc_ref, item.to_firestore())
    batch.set(movement_ref, movement.to_firestore())
    batch.commit()
    return item


def update_inventory(db: Client, access: BusinessAccess, inventory_id: str, update_in: InventoryUpdateIn) -> InventoryItem:
    """Sets a new quantity (a correction, e.g. after counting) and/or the low-stock alert level."""
    access.require(Permission.MANAGE_INVENTORY)
    doc_ref = inventory_collection(db, access.business_id).document(inventory_id)
    item = _read_stock(doc_ref)
    if update_in.quantity < item.reserved_quantity:
        raise bad_request(f"{item.reserved_quantity:g} are reserved for confirmed orders; quantity cannot be lower")

    change = update_in.quantity - item.quantity
    item.quantity = update_in.quantity
    item.reorder_level = update_in.reorder_level
    item.updated_at = current_time_ms()
    calculate_stock(item)

    batch = db.batch()
    batch.set(doc_ref, item.to_firestore())
    if change != 0:
        names = stock_names(db, access.business_id, item.product_id, item.variant_id, item.location_id)
        movement_ref, movement = new_movement(
            db, access.business_id, item, names, StockMovementType.CORRECTION, change, access.user
        )
        batch.set(movement_ref, movement.to_firestore())
    batch.commit()
    return item


def adjust_inventory(db: Client, access: BusinessAccess, inventory_id: str, adjust_in: InventoryAdjustIn) -> InventoryItem:
    """Adds or removes stock. Uses a transaction so two adjustments at once cannot overwrite each other."""
    access.require(Permission.MANAGE_INVENTORY)
    doc_ref = inventory_collection(db, access.business_id).document(inventory_id)
    item = _read_stock(doc_ref)
    names = stock_names(db, access.business_id, item.product_id, item.variant_id, item.location_id)
    return _adjust(db.transaction(), db, access, doc_ref, names, adjust_in)


@firestore.transactional
def _adjust(
    transaction: Transaction,
    db: Client,
    access: BusinessAccess,
    doc_ref: DocumentReference,
    names: StockNames,
    adjust_in: InventoryAdjustIn,
) -> InventoryItem:
    snapshot = doc_ref.get(transaction=transaction)
    if not snapshot.exists:
        raise not_found("Inventory record")
    item = InventoryItem.from_snapshot(snapshot)

    new_quantity = item.quantity + adjust_in.change
    if new_quantity < item.reserved_quantity:
        raise bad_request(f"Only {item.available_quantity:g} available; cannot remove {-adjust_in.change:g}")

    item.quantity = new_quantity
    item.updated_at = current_time_ms()
    movement_ref, movement = new_movement(
        db, access.business_id, item, names, StockMovementType.ADJUSTMENT, adjust_in.change, access.user, note=adjust_in.note
    )
    transaction.set(doc_ref, calculate_stock(item).to_firestore())
    transaction.set(movement_ref, movement.to_firestore())
    return item


def delete_inventory(db: Client, access: BusinessAccess, inventory_id: str) -> None:
    access.require(Permission.MANAGE_INVENTORY)
    doc_ref = inventory_collection(db, access.business_id).document(inventory_id)
    item = _read_stock(doc_ref)
    if item.reserved_quantity > 0:
        raise bad_request("Stock here is reserved for confirmed orders")

    batch = db.batch()
    batch.delete(doc_ref)
    if item.quantity != 0:
        removed = -item.quantity
        item.quantity = 0
        names = stock_names(db, access.business_id, item.product_id, item.variant_id, item.location_id)
        movement_ref, movement = new_movement(
            db, access.business_id, item, names, StockMovementType.RECORD_REMOVED, removed, access.user
        )
        batch.set(movement_ref, movement.to_firestore())
    batch.commit()


def _read_stock(doc_ref: DocumentReference) -> InventoryItem:
    """A stock record straight from Firestore (not the cache): we are about to change it."""
    snapshot = doc_ref.get()
    if not snapshot.exists:
        raise not_found("Inventory record")
    return InventoryItem.from_snapshot(snapshot)
