"""Products, their variants, and their price tiers."""

from google.cloud.firestore import Client, FieldFilter

from app.controllers import activity_controller, crud
from app.controllers.crud import bad_request, not_found
from app.core import cache
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
from app.schemas.enums import ActivityCategory, Permission
from app.schemas.product import PriceIn, ProductFormIn, ProductIn, VariantIn
from app.schemas.views import ProductFull
from app.utils.helpers import current_time_ms
from app.utils.parallel import run_parallel

# ---- Products ----------------------------------------------------------------------------


def list_products(db: Client, business_id: str) -> list[Product]:
    return crud.list_documents(products_collection(db, business_id), Product)


def get_product(db: Client, business_id: str, product_id: str) -> Product:
    return crud.get_document(products_collection(db, business_id), product_id, Product, "Product")


def create_product(db: Client, access: BusinessAccess, product_in: ProductIn) -> Product:
    access.require(Permission.MANAGE_PRODUCTS)
    _check_brand_and_category(db, access.business_id, product_in)
    product = crud.create_document(products_collection(db, access.business_id), Product, product_in)
    _record(db, access, product, "created")
    return product


def update_product(db: Client, access: BusinessAccess, product_id: str, product_in: ProductIn) -> Product:
    access.require(Permission.MANAGE_PRODUCTS)
    _check_brand_and_category(db, access.business_id, product_in)
    product = crud.update_document(products_collection(db, access.business_id), product_id, Product, product_in, "Product")
    _record(db, access, product, "updated")
    return product


def delete_product(db: Client, access: BusinessAccess, product_id: str) -> None:
    """Deletes the product with its variants, prices, and stock records. Past orders and sales are kept."""
    access.require(Permission.MANAGE_PRODUCTS)
    product = get_product(db, access.business_id, product_id)

    _delete_inventory_where(db, access.business_id, "productId", product_id)
    db.recursive_delete(products_collection(db, access.business_id).document(product_id))
    _record(db, access, product, "deleted")


PRODUCT_ACTIONS = {"created": "Product added", "updated": "Product updated", "deleted": "Product deleted"}


def _record(db: Client, access: BusinessAccess, product: Product, change: str) -> None:
    """Adds the change to the business's activity history (and notifies the team)."""
    activity_controller.record(
        db,
        access.business_id,
        ActivityCategory.PRODUCTS,
        f"product.{change}",
        f"{PRODUCT_ACTIONS[change]}: {product.product_name}",
        by=access,
        link="" if change == "deleted" else f"/products/{product.id}",
    )


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


def list_all_prices(db: Client, business_id: str) -> list[Price]:
    """Every price tier of every product in one call (e.g. to show prices in the product list)."""
    products = list_products(db, business_id)
    price_lists = run_parallel(*[lambda p=p: list_prices(db, business_id, p.id) for p in products])
    return [price for prices in price_lists for price in prices]


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


# ---- The product form: product + variants + price tiers in one step -----------------------


def get_product_full(db: Client, business_id: str, product_id: str) -> ProductFull:
    product = get_product(db, business_id, product_id)
    variants, prices = run_parallel(
        lambda: list_variants(db, business_id, product_id),
        lambda: list_prices(db, business_id, product_id),
    )
    return ProductFull(product=product, variants=variants, prices=prices)


def save_product_full(
    db: Client, access: BusinessAccess, form: ProductFormIn, product_id: str | None = None
) -> ProductFull:
    """Creates (product_id=None) or updates a product together with its variants and price tiers.

    Variants and tiers in the form are created or updated; ones missing from the form are deleted.
    Everything is saved in one batch: either all of it is saved, or none of it.
    """
    access.require(Permission.MANAGE_PRODUCTS)
    business_id = access.business_id
    _check_brand_and_category(db, business_id, form)
    now = current_time_ms()

    # What exists now (read straight from Firestore, since we are about to change it)
    existing_product = crud.read_fresh(products_collection(db, business_id).document(product_id), Product) if product_id else None
    if product_id and existing_product is None:
        raise not_found("Product")
    # document(None) makes a new random id
    product_ref = products_collection(db, business_id).document(product_id)
    old_variants = {v.id: v for v in _read_all(variants_collection(db, business_id, product_ref.id), Variant)} if product_id else {}
    old_prices = {p.id: p for p in _read_all(prices_collection(db, business_id, product_ref.id), Price)} if product_id else {}

    batch = db.batch()
    product = Product(
        **form.model_dump(exclude={"variants", "prices"}),
        id=product_ref.id,
        created_at=existing_product.created_at if existing_product else now,
        updated_at=now,
    )
    batch.set(product_ref, product.to_firestore())

    # Variants: keep the form's order (each new one is 1 ms "younger" than the one before)
    variant_ids_by_key: dict[str, str] = {}
    variants: list[Variant] = []
    for position, draft in enumerate(form.variants):
        existing = old_variants.get(draft.key)
        ref = variants_collection(db, business_id, product_ref.id).document(existing.id if existing else None)
        variant_ids_by_key[draft.key] = ref.id
        variant = Variant(
            **draft.model_dump(exclude={"key"}),
            id=ref.id,
            product_id=product_ref.id,
            created_at=existing.created_at if existing else now + position,
            updated_at=now,
        )
        batch.set(ref, variant.to_firestore())
        variants.append(variant)

    for removed_id in set(old_variants) - set(variant_ids_by_key.values()):
        _delete_variant_stock(db, batch, business_id, old_variants[removed_id])
        batch.delete(variants_collection(db, business_id, product_ref.id).document(removed_id))

    # Price tiers
    prices: list[Price] = []
    for position, draft in enumerate(form.prices):
        existing = old_prices.get(draft.id) if draft.id else None
        ref = prices_collection(db, business_id, product_ref.id).document(existing.id if existing else None)
        price = Price(
            **draft.model_dump(exclude={"id", "variant_key", "variant_id", "currency"}),
            variant_id=variant_ids_by_key.get(draft.variant_key) if draft.variant_key else None,
            currency=access.business.currency,
            product_id=product_ref.id,
            id=ref.id,
            created_at=existing.created_at if existing else now + position,
            updated_at=now,
        )
        batch.set(ref, price.to_firestore())
        prices.append(price)

    for removed_id in set(old_prices) - {price.id for price in prices}:
        batch.delete(prices_collection(db, business_id, product_ref.id).document(removed_id))

    batch.commit()
    cache.bump(cache.business_scope(business_id), cache.DIRECTORY)
    _record(db, access, product, "updated" if existing_product else "created")
    return ProductFull(product=product, variants=variants, prices=prices)


def _read_all(collection, model_class) -> list:
    """Every document in a collection, straight from Firestore (no cache)."""
    return [model_class.from_snapshot(snapshot) for snapshot in collection.stream()]


def _delete_variant_stock(db: Client, batch, business_id: str, variant: Variant) -> None:
    """A removed variant's empty stock records are deleted with it. Stock that is still there blocks
    the removal, so the stock history always adds up."""
    query = inventory_collection(db, business_id).where(filter=FieldFilter("variantId", "==", variant.id))
    for snapshot in query.stream():
        data = snapshot.to_dict()
        if data.get("quantity", 0) or data.get("reservedQuantity", 0):
            raise bad_request(
                f"The variant \"{variant.variant_name}\" still has stock. Remove its stock in Inventory before removing it."
            )
        batch.delete(snapshot.reference)
