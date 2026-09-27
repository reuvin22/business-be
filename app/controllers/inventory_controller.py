from google.cloud import firestore
from google.cloud.firestore import Client, DocumentReference, Transaction

from app.controllers import crud
from app.controllers.crud import bad_request, not_found
from app.controllers.product_controller import get_product, get_variant
from app.dependencies.business_access import BusinessAccess
from app.models.inventory import InventoryItem, inventory_collection, inventory_document
from app.models.profile import locations_collection
from app.schemas.enums import Permission, StockStatus
from app.schemas.inventory import InventoryAdjustIn, InventoryIn, InventoryUpdateIn
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
    doc_ref.set(item.to_firestore())
    return item


def update_inventory(db: Client, access: BusinessAccess, inventory_id: str, update_in: InventoryUpdateIn) -> InventoryItem:
    access.require(Permission.MANAGE_INVENTORY)
    item = crud.get_document(inventory_collection(db, access.business_id), inventory_id, InventoryItem, "Inventory record")
    if update_in.quantity < item.reserved_quantity:
        raise bad_request(f"{item.reserved_quantity:g} are reserved for confirmed orders; quantity cannot be lower")

    item.quantity = update_in.quantity
    item.reorder_level = update_in.reorder_level
    item.updated_at = current_time_ms()
    calculate_stock(item)
    inventory_collection(db, access.business_id).document(inventory_id).set(item.to_firestore())
    return item


def adjust_inventory(db: Client, access: BusinessAccess, inventory_id: str, adjust_in: InventoryAdjustIn) -> InventoryItem:
    """Adds or removes stock. Uses a transaction so two adjustments at once cannot overwrite each other."""
    access.require(Permission.MANAGE_INVENTORY)
    doc_ref = inventory_collection(db, access.business_id).document(inventory_id)
    return _adjust(db.transaction(), doc_ref, adjust_in.change)


@firestore.transactional
def _adjust(transaction: Transaction, doc_ref: DocumentReference, change: float) -> InventoryItem:
    snapshot = doc_ref.get(transaction=transaction)
    if not snapshot.exists:
        raise not_found("Inventory record")
    item = InventoryItem.from_snapshot(snapshot)

    new_quantity = item.quantity + change
    if new_quantity < item.reserved_quantity:
        raise bad_request(f"Only {item.available_quantity:g} available; cannot remove {-change:g}")

    item.quantity = new_quantity
    item.updated_at = current_time_ms()
    transaction.set(doc_ref, calculate_stock(item).to_firestore())
    return item


def delete_inventory(db: Client, access: BusinessAccess, inventory_id: str) -> None:
    access.require(Permission.MANAGE_INVENTORY)
    item = crud.get_document(inventory_collection(db, access.business_id), inventory_id, InventoryItem, "Inventory record")
    if item.reserved_quantity > 0:
        raise bad_request("Stock here is reserved for confirmed orders")
    inventory_collection(db, access.business_id).document(inventory_id).delete()
