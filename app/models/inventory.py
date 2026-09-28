from google.cloud.firestore import Client, CollectionReference, DocumentReference

from app.models.base import FirestoreModel
from app.models.business import business_subcollection
from app.schemas.enums import StockMovementType, StockStatus
from app.schemas.inventory import InventoryIn

# Firestore location:  businesses/{businessId}/inventory/{inventoryId}
#
# The id is built from product + variant + location (see inventory_id below), so there is
# exactly one stock record per product (or variant) per location.


class InventoryItem(InventoryIn, FirestoreModel):
    reserved_quantity: float = 0  # held for confirmed orders that have not shipped yet
    available_quantity: float = 0  # quantity - reserved_quantity
    stock_status: StockStatus = StockStatus.OUT_OF_STOCK


class StockMovement(FirestoreModel):
    """One change to a quantity on hand. Together they are the stock history.

    Firestore location:  businesses/{businessId}/stockMovements/{id}
    Names are copied in, so the history still reads well after a product is renamed or deleted.
    """

    product_id: str
    variant_id: str | None = None
    location_id: str
    product_name: str = ""
    variant_name: str = ""
    location_name: str = ""
    movement_type: StockMovementType
    change: float  # + added, - taken out
    quantity_after: float  # quantity on hand right after this change
    note: str = ""
    reference_id: str = ""  # the sale or order that caused it
    reference_label: str = ""  # e.g. the order number
    by_uid: str = ""
    by_name: str = ""


def stock_movements_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "stockMovements")


def inventory_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "inventory")


def inventory_id(product_id: str, variant_id: str | None, location_id: str) -> str:
    return f"{product_id}__{variant_id or 'base'}__{location_id}"


def inventory_document(
    db: Client, business_id: str, product_id: str, variant_id: str | None, location_id: str
) -> DocumentReference:
    return inventory_collection(db, business_id).document(inventory_id(product_id, variant_id, location_id))
