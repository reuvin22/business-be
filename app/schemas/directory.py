"""What other businesses see about a business (its public profile and catalog)."""

import datetime

from app.models.product import Price, Variant
from app.models.profile import Brand, DeliveryZone, Location, SocialLink
from app.models.settings import DeliverySettings, PaymentTerms, ReturnPolicy, SupplierProfile
from app.schemas.base import CamelModel
from app.schemas.business import BusinessPublicDetails
from app.schemas.contact import PublicContact
from app.schemas.enums import PaymentType
from app.schemas.product import OrderRules, ProductImage, Specification
from app.schemas.trust import PublicCertification


class PublicProfile(CamelModel):
    business: BusinessPublicDetails
    locations: list[Location]
    contacts: list[PublicContact]
    brands: list[Brand]
    supplier_profile: SupplierProfile
    delivery: DeliverySettings
    delivery_zones: list[DeliveryZone]
    payment_terms: PaymentTerms
    return_policy: ReturnPolicy
    payment_types: list[PaymentType]  # only the types; account numbers stay private
    certifications: list[PublicCertification]
    social_links: list[SocialLink]


class MyCustomerPrice(CamelModel):
    """A private price the seller set for the viewing buyer."""

    variant_id: str | None
    price: float
    minimum_quantity: int
    effective_from: datetime.date | None
    effective_until: datetime.date | None


class PublicProduct(CamelModel):
    id: str
    product_name: str
    sku: str
    barcode: str
    category_id: str | None
    brand_id: str | None
    description: str
    specifications: list[Specification]
    unit: str
    images: list[ProductImage]
    order_rules: OrderRules
    variants: list[Variant]
    prices: list[Price]  # only active, current price tiers
    customer_prices: list[MyCustomerPrice] = []  # only when viewing as one of the seller's customers
