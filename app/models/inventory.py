from google.cloud.firestore import Client, CollectionReference, DocumentReference

from app.models.base import FirestoreModel
from app.models.business import business_subcollection
from app.schemas.enums import StockStatus
from app.schemas.inventory import InventoryIn

# Firestore location:  businesses/{businessId}/inventory/{inventoryId}
#
# The id is built from product + variant + location (see inventory_id below), so there is
# exactly one stock record per product (or variant) per location.


class InventoryItem(InventoryIn, FirestoreModel):
    reserved_quantity: float = 0  # held for confirmed orders that have not shipped yet
    available_quantity: float = 0  # quantity - reserved_quantity
    stock_status: StockStatus = StockStatus.OUT_OF_STOCK


def inventory_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "inventory")


def inventory_id(product_id: str, variant_id: str | None, location_id: str) -> str:
    return f"{product_id}__{variant_id or 'base'}__{location_id}"


def inventory_document(
    db: Client, business_id: str, product_id: str, variant_id: str | None, location_id: str
) -> DocumentReference:
    return inventory_collection(db, business_id).document(inventory_id(product_id, variant_id, location_id))
