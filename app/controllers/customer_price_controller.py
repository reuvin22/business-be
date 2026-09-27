from google.cloud.firestore import Client, FieldFilter

from app.controllers import crud
from app.controllers.business_controller import find_business
from app.controllers.crud import bad_request, not_found
from app.controllers.product_controller import get_product, get_variant
from app.core import cache
from app.dependencies.business_access import BusinessAccess
from app.models.network import CustomerPrice, customer_prices_collection
from app.schemas.enums import Permission
from app.schemas.network import CustomerPriceIn


def list_customer_prices(db: Client, business_id: str) -> list[CustomerPrice]:
    """All private prices a seller has set (seller's team only)."""
    return crud.list_documents(customer_prices_collection(db, business_id), CustomerPrice)


def list_prices_for_customer(db: Client, seller_id: str, customer_id: str) -> list[CustomerPrice]:
    """The private prices one seller gives one customer (cached with the seller's data)."""

    def read() -> list[CustomerPrice]:
        query = customer_prices_collection(db, seller_id).where(filter=FieldFilter("customerBusinessId", "==", customer_id))
        return [CustomerPrice.from_snapshot(snapshot) for snapshot in query.stream()]

    return cache.cached_models(cache.business_scope(seller_id), f"customer-prices:{customer_id}", CustomerPrice, read)


def create_customer_price(db: Client, access: BusinessAccess, price_in: CustomerPriceIn) -> CustomerPrice:
    access.require(Permission.MANAGE_PRODUCTS)
    customer_name = _check(db, access, price_in)
    return crud.create_document(
        customer_prices_collection(db, access.business_id), CustomerPrice, price_in, customer_business_name=customer_name
    )


def update_customer_price(db: Client, access: BusinessAccess, price_id: str, price_in: CustomerPriceIn) -> CustomerPrice:
    access.require(Permission.MANAGE_PRODUCTS)
    customer_name = _check(db, access, price_in)
    return crud.update_document(
        customer_prices_collection(db, access.business_id),
        price_id,
        CustomerPrice,
        price_in,
        "Customer price",
        customer_business_name=customer_name,
    )


def delete_customer_price(db: Client, access: BusinessAccess, price_id: str) -> None:
    access.require(Permission.MANAGE_PRODUCTS)
    crud.delete_document(customer_prices_collection(db, access.business_id), price_id, "Customer price")


def _check(db: Client, access: BusinessAccess, price_in: CustomerPriceIn) -> str:
    """Checks the product and customer exist. Returns the customer's name."""
    get_product(db, access.business_id, price_in.product_id)
    if price_in.variant_id:
        get_variant(db, access.business_id, price_in.product_id, price_in.variant_id)
    if price_in.customer_business_id == access.business_id:
        raise bad_request("You cannot set a customer price for your own business")
    customer = find_business(db, price_in.customer_business_id)
    if customer is None:
        raise not_found("Customer business")
    return customer.business_name
