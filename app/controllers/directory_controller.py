"""The business directory: what any logged-in user can see about ACTIVE businesses."""

import datetime

from google.cloud.firestore import Client, FieldFilter

from app.controllers import settings_controller
from app.controllers.brand_controller import list_brands
from app.controllers.contact_controller import list_contacts
from app.controllers.crud import forbidden, not_found
from app.controllers.customer_price_controller import list_prices_for_customer
from app.controllers.delivery_zone_controller import list_delivery_zones
from app.controllers.location_controller import list_locations
from app.controllers.payment_method_controller import list_accepted_payment_types
from app.controllers.pricing import is_current
from app.controllers.product_controller import list_prices
from app.controllers.review_controller import list_reviews
from app.controllers.trust_controller import list_certifications, list_social_links
from app.models.business import Business, business_document, businesses_collection
from app.models.member import members_collection
from app.models.network import Review
from app.models.product import Product, Variant, products_collection, variants_collection
from app.schemas.business import BusinessPublicDetails, BusinessSummary
from app.schemas.contact import PublicContact
from app.schemas.directory import MyCustomerPrice, PublicProduct, PublicProfile
from app.schemas.enums import ActiveStatus, BusinessStatus, BusinessType, ProductStatus, VerificationStatus, Visibility
from app.schemas.trust import PublicCertification
from app.schemas.user import CurrentUser


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
    switch to a search service (e.g. Algolia, Typesense) when it grows beyond that."""
    query = businesses_collection(db).where(filter=FieldFilter("businessStatus", "==", BusinessStatus.ACTIVE.value))
    businesses = [Business.from_snapshot(snapshot) for snapshot in query.stream()]

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


def _get_active_business(db: Client, business_id: str) -> Business:
    snapshot = business_document(db, business_id).get()
    if not snapshot.exists:
        raise not_found("Business")
    business = Business.from_snapshot(snapshot)
    if business.business_status != BusinessStatus.ACTIVE:
        raise not_found("Business")
    return business


def get_public_profile(db: Client, business_id: str) -> PublicProfile:
    business = _get_active_business(db, business_id)
    return PublicProfile(
        business=BusinessPublicDetails.model_validate(business),
        locations=list_locations(db, business_id),
        contacts=[PublicContact.model_validate(c) for c in list_contacts(db, business_id) if c.show_on_profile],
        brands=[b for b in list_brands(db, business_id) if b.status == ActiveStatus.ACTIVE],
        supplier_profile=settings_controller.get_supplier_profile(db, business_id),
        delivery=settings_controller.get_delivery(db, business_id),
        delivery_zones=list_delivery_zones(db, business_id),
        payment_terms=settings_controller.get_payment_terms(db, business_id),
        return_policy=settings_controller.get_return_policy(db, business_id),
        payment_types=list_accepted_payment_types(db, business_id),
        certifications=[PublicCertification.model_validate(c) for c in list_certifications(db, business_id)],
        social_links=list_social_links(db, business_id),
    )


def list_public_products(
    db: Client, user: CurrentUser, business_id: str, buyer_business_id: str | None = None
) -> list[PublicProduct]:
    """The seller's public catalog. Pass buyer_business_id (one of your businesses) to also see
    the private prices the seller gave that business."""
    _get_active_business(db, business_id)

    customer_prices = []
    if buyer_business_id:
        member = members_collection(db, buyer_business_id).document(user.uid).get()
        if not member.exists or member.to_dict().get("status") != "ACTIVE":
            raise forbidden("You are not a member of that buyer business")
        customer_prices = list_prices_for_customer(db, business_id, buyer_business_id)

    today = datetime.date.today()
    query = products_collection(db, business_id).where(filter=FieldFilter("visibility", "==", Visibility.PUBLIC.value))
    products = [Product.from_snapshot(s) for s in query.stream()]
    products = sorted((p for p in products if p.status == ProductStatus.ACTIVE), key=lambda p: p.product_name.lower())

    # Note: this reads variants and prices for each product. Fine for a normal catalog size.
    results = []
    for product in products:
        variants = [
            Variant.from_snapshot(s)
            for s in variants_collection(db, business_id, product.id).order_by("createdAt").stream()
        ]
        prices = [
            p
            for p in list_prices(db, business_id, product.id)
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
