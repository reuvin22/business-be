"""Walk-in (over-the-counter) sales. Each sale takes stock out of one location."""

from google.cloud import firestore
from google.cloud.firestore import Client, DocumentReference, Transaction

from app.controllers import crud
from app.controllers.crud import bad_request, not_found
from app.controllers.inventory_controller import calculate_stock
from app.controllers.product_controller import get_product, get_variant
from app.dependencies.business_access import BusinessAccess
from app.models.inventory import InventoryItem, inventory_document
from app.models.trade import Sale, sales_collection
from app.schemas.enums import Permission
from app.schemas.sale import SaleIn
from app.utils.helpers import current_time_ms


def list_sales(db: Client, business_id: str) -> list[Sale]:
    return crud.list_documents(sales_collection(db, business_id), Sale)


def record_sale(db: Client, access: BusinessAccess, sale_in: SaleIn) -> Sale:
    access.require(Permission.MANAGE_INVENTORY)
    product = get_product(db, access.business_id, sale_in.product_id)
    variant = get_variant(db, access.business_id, product.id, sale_in.variant_id) if sale_in.variant_id else None

    now = current_time_ms()
    sale_ref = sales_collection(db, access.business_id).document()
    sale = Sale(
        **sale_in.model_dump(),
        id=sale_ref.id,
        created_at=now,
        updated_at=now,
        product_name=product.product_name,
        variant_name=variant.variant_name if variant else "",
        unit_cost=product.cost_price,
    )
    stock_ref = inventory_document(db, access.business_id, product.id, sale_in.variant_id, sale_in.location_id)
    return _record(db.transaction(), stock_ref, sale_ref, sale)


@firestore.transactional
def _record(transaction: Transaction, stock_ref: DocumentReference, sale_ref: DocumentReference, sale: Sale) -> Sale:
    """Saves the sale and takes it out of stock together, so stock can never be sold twice."""
    snapshot = stock_ref.get(transaction=transaction)
    if not snapshot.exists:
        raise bad_request("This product has no stock at that location")
    stock = InventoryItem.from_snapshot(snapshot)
    if sale.quantity > stock.available_quantity:
        raise bad_request(f"Only {stock.available_quantity:g} available at that location")

    stock.quantity -= sale.quantity
    stock.updated_at = current_time_ms()
    transaction.set(stock_ref, calculate_stock(stock).to_firestore())
    transaction.set(sale_ref, sale.to_firestore())
    return sale


def delete_sale(db: Client, access: BusinessAccess, sale_id: str) -> None:
    """Removes a sale and puts the quantity back into stock (if the stock record still exists)."""
    access.require(Permission.MANAGE_INVENTORY)
    sale_ref = sales_collection(db, access.business_id).document(sale_id)
    _undo(db.transaction(), db, access.business_id, sale_ref)


@firestore.transactional
def _undo(transaction: Transaction, db: Client, business_id: str, sale_ref: DocumentReference) -> None:
    sale_snapshot = sale_ref.get(transaction=transaction)
    if not sale_snapshot.exists:
        raise not_found("Sale")
    sale = Sale.from_snapshot(sale_snapshot)

    stock_ref = inventory_document(db, business_id, sale.product_id, sale.variant_id, sale.location_id)
    stock_snapshot = stock_ref.get(transaction=transaction)
    if stock_snapshot.exists:
        stock = InventoryItem.from_snapshot(stock_snapshot)
        stock.quantity += sale.quantity
        stock.updated_at = current_time_ms()
        transaction.set(stock_ref, calculate_stock(stock).to_firestore())

    transaction.delete(sale_ref)
