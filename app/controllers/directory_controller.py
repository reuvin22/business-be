"""The business directory: what any logged-in user can see about ACTIVE businesses."""

import datetime

from google.cloud.firestore import Client, FieldFilter

from app.controllers import crud, settings_controller
from app.controllers.brand_controller import list_brands
from app.controllers.contact_controller import list_contacts
from app.controllers.crud import forbidden, not_found
from app.controllers.customer_price_controller import list_prices_for_customer
from app.controllers.delivery_zone_controller import list_delivery_zones
from app.controllers.location_controller import list_locations
from app.controllers.payment_method_controller import list_accepted_payment_types
from app.controllers.pricing import is_current
from app.controllers.product_controller import list_prices, list_variants
from app.controllers.review_controller import list_reviews
from app.controllers.trust_controller import list_certifications, list_social_links
from app.core import cache
from app.dependencies.business_access import load_business
from app.models.business import Business, businesses_collection
from app.models.member import members_collection
from app.models.network import Review
from app.models.product import Product, products_collection
from app.schemas.business import BusinessPublicDetails, BusinessSummary
from app.schemas.contact import PublicContact
from app.schemas.directory import MyCustomerPrice, PublicProduct, PublicProfile
from app.schemas.enums import ActiveStatus, BusinessStatus, BusinessType, ProductStatus, VerificationStatus, Visibility
from app.schemas.trust import PublicCertification
from app.schemas.user import CurrentUser
from app.utils.parallel import run_parallel


def search_businesses(
    db: Client,
    text: str = "",
    business_type: BusinessType | None = None,
    capability: str = "",
    category_id: str = "",
    city: str = "",
    verified_only: bool = False,
) -> list[BusinessSummary]:
    """Filters the directory. Firestore can only filter on one field here without extra indexes,
    so we load active businesses and filter the rest in Python. Fine for thousands of businesses;
    switch to a search service (e.g. Algolia, Typesense) when it grows beyond that.

    The list of active businesses is cached, so a search filters in memory instead of reading the database."""
    businesses = _active_businesses(db)

    text = text.strip().lower()
    results = []
    for b in businesses:
        searchable = f"{b.business_name} {b.trade_name} {b.business_description} {b.industry}".lower()
        if text and text not in searchable:
            continue
        if business_type and business_type not in b.business_types:
            continue
        if capability and capability not in b.capabilities:
            continue
        if category_id and category_id not in b.category_ids:
            continue
        if city and city.strip().lower() not in b.primary_city.lower():
            continue
        if verified_only and b.verification_status != VerificationStatus.VERIFIED:
            continue
        results.append(BusinessSummary.model_validate(b))

    return sorted(results, key=lambda b: (-b.rating_average, b.business_name.lower()))


def _active_businesses(db: Client) -> list[Business]:
    def read() -> list[Business]:
        query = businesses_collection(db).where(filter=FieldFilter("businessStatus", "==", BusinessStatus.ACTIVE.value))
        return [Business.from_snapshot(snapshot) for snapshot in query.stream()]

    return cache.cached_models(cache.DIRECTORY, "active-businesses", Business, read)


def _get_active_business(db: Client, business_id: str) -> Business:
    business = load_business(db, business_id)
    if business is None or business.business_status != BusinessStatus.ACTIVE:
        raise not_found("Business")
    return business


def get_public_profile(db: Client, business_id: str) -> PublicProfile:
    """The whole public profile, cached as one entry (rebuilt when the business changes)."""
    return cache.cached_model(
        cache.business_scope(business_id), "public-profile", PublicProfile, lambda: _build_public_profile(db, business_id)
    )


def _build_public_profile(db: Client, business_id: str) -> PublicProfile:
    business = _get_active_business(db, business_id)
    # These reads don't depend on each other, so they run at the same time
    (
        locations,
        contacts,
        brands,
        supplier_profile,
        delivery,
        delivery_zones,
        payment_terms,
        return_policy,
        payment_types,
        certifications,
        social_links,
    ) = run_parallel(
        lambda: list_locations(db, business_id),
        lambda: list_contacts(db, business_id),
        lambda: list_brands(db, business_id),
        lambda: settings_controller.get_supplier_profile(db, business_id),
        lambda: settings_controller.get_delivery(db, business_id),
        lambda: list_delivery_zones(db, business_id),
        lambda: settings_controller.get_payment_terms(db, business_id),
        lambda: settings_controller.get_return_policy(db, business_id),
        lambda: list_accepted_payment_types(db, business_id),
        lambda: list_certifications(db, business_id),
        lambda: list_social_links(db, business_id),
    )
    return PublicProfile(
        business=BusinessPublicDetails.model_validate(business),
        locations=locations,
        contacts=[PublicContact.model_validate(c) for c in contacts if c.show_on_profile],
        brands=[b for b in brands if b.status == ActiveStatus.ACTIVE],
        supplier_profile=supplier_profile,
        delivery=delivery,
        delivery_zones=delivery_zones,
        payment_terms=payment_terms,
        return_policy=return_policy,
        payment_types=payment_types,
        certifications=[PublicCertification.model_validate(c) for c in certifications],
        social_links=social_links,
    )


def list_public_products(
    db: Client, user: CurrentUser, business_id: str, buyer_business_id: str | None = None
) -> list[PublicProduct]:
    """The seller's public catalog. Pass buyer_business_id (one of your businesses) to also see
    the private prices the seller gave that business."""
    if buyer_business_id:
        member = members_collection(db, buyer_business_id).document(user.uid).get()
        if not member.exists or member.to_dict().get("status") != "ACTIVE":
            raise forbidden("You are not a member of that buyer business")

    # Cached per buyer, and per day (price tiers can start or end at midnight)
    today = datetime.date.today()
    return cache.cached_models(
        cache.business_scope(business_id),
        f"public-products:{buyer_business_id or 'anyone'}:{today}",
        PublicProduct,
        lambda: _build_public_products(db, business_id, buyer_business_id, today),
    )


def _build_public_products(
    db: Client, business_id: str, buyer_business_id: str | None, today: datetime.date
) -> list[PublicProduct]:
    _get_active_business(db, business_id)
    customer_prices = list_prices_for_customer(db, business_id, buyer_business_id) if buyer_business_id else []

    public = products_collection(db, business_id).where(filter=FieldFilter("visibility", "==", Visibility.PUBLIC.value))
    public_and_active = public.where(filter=FieldFilter("status", "==", ProductStatus.ACTIVE.value))
    products = [Product.from_snapshot(s) for s in crud.stream_indexed(public_and_active, fallback=public)]
    products = sorted((p for p in products if p.status == ProductStatus.ACTIVE), key=lambda p: p.product_name.lower())

    # Variants and prices of every product are read at the same time, not one product after another
    variant_lists = run_parallel(*[lambda p=p: list_variants(db, business_id, p.id) for p in products])
    price_lists = run_parallel(*[lambda p=p: list_prices(db, business_id, p.id) for p in products])

    results = []
    for product, variants, all_prices in zip(products, variant_lists, price_lists):
        prices = [
            p
            for p in all_prices
            if p.status == ActiveStatus.ACTIVE and is_current(p.effective_from, p.effective_until, today)
        ]
        mine = [
            MyCustomerPrice.model_validate(cp)
            for cp in customer_prices
            if cp.product_id == product.id and is_current(cp.effective_from, cp.effective_until, today)
        ]
        results.append(
            PublicProduct(
                **product.model_dump(exclude={"cost_price", "status", "visibility", "created_at", "updated_at"}),
                variants=[v for v in variants if v.status == ActiveStatus.ACTIVE],
                prices=prices,
                customer_prices=mine,
            )
        )
    return results


def list_public_reviews(db: Client, business_id: str) -> list[Review]:
    _get_active_business(db, business_id)
    return list_reviews(db, business_id)
