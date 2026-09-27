"""Products, their variants, and their price tiers."""

from google.cloud.firestore import Client, FieldFilter

from app.controllers import crud
from app.controllers.crud import bad_request
from app.dependencies.business_access import BusinessAccess
from app.models.category import categories_collection
from app.models.inventory import inventory_collection
from app.models.product import (
    Price,
    Product,
    Variant,
    prices_collection,
    products_collection,
    variants_collection,
)
from app.models.profile import brands_collection
from app.schemas.enums import Permission
from app.schemas.product import PriceIn, ProductIn, VariantIn
from app.utils.parallel import run_parallel

# ---- Products ----------------------------------------------------------------------------


def list_products(db: Client, business_id: str) -> list[Product]:
    return crud.list_documents(products_collection(db, business_id), Product)


def get_product(db: Client, business_id: str, product_id: str) -> Product:
    return crud.get_document(products_collection(db, business_id), product_id, Product, "Product")


def create_product(db: Client, access: BusinessAccess, product_in: ProductIn) -> Product:
    access.require(Permission.MANAGE_PRODUCTS)
    _check_brand_and_category(db, access.business_id, product_in)
    return crud.create_document(products_collection(db, access.business_id), Product, product_in)


def update_product(db: Client, access: BusinessAccess, product_id: str, product_in: ProductIn) -> Product:
    access.require(Permission.MANAGE_PRODUCTS)
    _check_brand_and_category(db, access.business_id, product_in)
    return crud.update_document(products_collection(db, access.business_id), product_id, Product, product_in, "Product")


def delete_product(db: Client, access: BusinessAccess, product_id: str) -> None:
    """Deletes the product with its variants, prices, and stock records. Past orders and sales are kept."""
    access.require(Permission.MANAGE_PRODUCTS)
    get_product(db, access.business_id, product_id)

    _delete_inventory_where(db, access.business_id, "productId", product_id)
    db.recursive_delete(products_collection(db, access.business_id).document(product_id))


def _check_brand_and_category(db: Client, business_id: str, product_in: ProductIn) -> None:
    if product_in.brand_id and not brands_collection(db, business_id).document(product_in.brand_id).get().exists:
        raise bad_request("Brand not found")
    if product_in.category_id and not categories_collection(db).document(product_in.category_id).get().exists:
        raise bad_request("Category not found")


def _delete_inventory_where(db: Client, business_id: str, field: str, value: str) -> None:
    query = inventory_collection(db, business_id).where(filter=FieldFilter(field, "==", value))
    for snapshot in query.stream():
        snapshot.reference.delete()


# ---- Variants ----------------------------------------------------------------------------


def list_variants(db: Client, business_id: str, product_id: str) -> list[Variant]:
    get_product(db, business_id, product_id)
    return crud.list_documents(variants_collection(db, business_id, product_id), Variant)


def list_all_variants(db: Client, business_id: str) -> list[Variant]:
    """Every variant of every product in one call (read at the same time, not product by product)."""
    products = list_products(db, business_id)
    variant_lists = run_parallel(*[lambda p=p: list_variants(db, business_id, p.id) for p in products])
    return [variant for variants in variant_lists for variant in variants]


def get_variant(db: Client, business_id: str, product_id: str, variant_id: str) -> Variant:
    return crud.get_document(variants_collection(db, business_id, product_id), variant_id, Variant, "Variant")


def create_variant(db: Client, access: BusinessAccess, product_id: str, variant_in: VariantIn) -> Variant:
    access.require(Permission.MANAGE_PRODUCTS)
    get_product(db, access.business_id, product_id)
    return crud.create_document(
        variants_collection(db, access.business_id, product_id), Variant, variant_in, product_id=product_id
    )


def update_variant(db: Client, access: BusinessAccess, product_id: str, variant_id: str, variant_in: VariantIn) -> Variant:
    access.require(Permission.MANAGE_PRODUCTS)
    return crud.update_document(
        variants_collection(db, access.business_id, product_id), variant_id, Variant, variant_in, "Variant"
    )


def delete_variant(db: Client, access: BusinessAccess, product_id: str, variant_id: str) -> None:
    """Deletes the variant with its own prices and stock records."""
    access.require(Permission.MANAGE_PRODUCTS)
    crud.delete_document(variants_collection(db, access.business_id, product_id), variant_id, "Variant")

    for price in list_prices(db, access.business_id, product_id):
        if price.variant_id == variant_id:
            prices_collection(db, access.business_id, product_id).document(price.id).delete()
    _delete_inventory_where(db, access.business_id, "variantId", variant_id)


# ---- Price tiers -------------------------------------------------------------------------


def list_prices(db: Client, business_id: str, product_id: str) -> list[Price]:
    return crud.list_documents(prices_collection(db, business_id, product_id), Price)


def create_price(db: Client, access: BusinessAccess, product_id: str, price_in: PriceIn) -> Price:
    access.require(Permission.MANAGE_PRODUCTS)
    _check_price(db, access, product_id, price_in)
    return crud.create_document(prices_collection(db, access.business_id, product_id), Price, price_in, product_id=product_id)


def update_price(db: Client, access: BusinessAccess, product_id: str, price_id: str, price_in: PriceIn) -> Price:
    access.require(Permission.MANAGE_PRODUCTS)
    _check_price(db, access, product_id, price_in)
    return crud.update_document(prices_collection(db, access.business_id, product_id), price_id, Price, price_in, "Price")


def delete_price(db: Client, access: BusinessAccess, product_id: str, price_id: str) -> None:
    access.require(Permission.MANAGE_PRODUCTS)
    crud.delete_document(prices_collection(db, access.business_id, product_id), price_id, "Price")


def _check_price(db: Client, access: BusinessAccess, product_id: str, price_in: PriceIn) -> None:
    get_product(db, access.business_id, product_id)
    if price_in.variant_id:
        get_variant(db, access.business_id, product_id, price_in.variant_id)
    if price_in.currency != access.business.currency:
        raise bad_request(f"Prices must be in the business currency ({access.business.currency})")
