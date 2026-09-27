import datetime

from pydantic import Field, model_validator

from app.schemas.base import CamelModel, UrlText, check_date_order
from app.schemas.enums import ActiveStatus, BusinessType, PriceType, ProductStatus, Visibility


class ProductImage(CamelModel):
    image_url: UrlText = Field(min_length=1)
    sort_order: int = 0
    is_primary: bool = False


class Specification(CamelModel):
    """One row of the spec sheet, e.g. name="Shelf life", value="12 months"."""

    name: str = Field(min_length=1)
    value: str = ""


class OrderRules(CamelModel):
    """Purchasing rules for other businesses (section 10). Example: MOQ 50, multiples of 10, 3 days lead time."""

    minimum_order_quantity: int = Field(default=1, ge=1)
    maximum_order_quantity: int | None = Field(default=None, ge=1)
    order_multiple: int = Field(default=1, ge=1)
    minimum_order_value: float | None = Field(default=None, ge=0)
    lead_time_days: int | None = Field(default=None, ge=0)
    preorder_allowed: bool = False

    @model_validator(mode="after")
    def check_quantities(self):
        if self.maximum_order_quantity and self.maximum_order_quantity < self.minimum_order_quantity:
            raise ValueError("maximum order quantity must be at least the minimum order quantity")
        return self


class ProductIn(CamelModel):
    """A product in the catalog (section 6). Images, specs, and order rules are kept inside the product."""

    product_name: str = Field(min_length=1)
    sku: str = ""
    barcode: str = ""
    category_id: str | None = None
    brand_id: str | None = None
    description: str = ""
    specifications: list[Specification] = []
    unit: str = "pcs"
    status: ProductStatus = ProductStatus.ACTIVE
    visibility: Visibility = Visibility.PUBLIC
    images: list[ProductImage] = []
    order_rules: OrderRules = OrderRules()
    # Private: what one unit costs you. Used for profit margin on the dashboard, never shown publicly.
    cost_price: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def one_primary_image(self):
        """Sorts images and makes sure exactly one is the primary (the first one, if none was chosen)."""
        self.images.sort(key=lambda image: image.sort_order)
        primary_index = next((i for i, image in enumerate(self.images) if image.is_primary), 0)
        for i, image in enumerate(self.images):
            image.is_primary = i == primary_index
        return self


class VariantIn(CamelModel):
    """One version of a product (section 7), e.g. Coca-Cola 1.5L."""

    variant_name: str = Field(min_length=1)
    sku: str = ""
    barcode: str = ""
    attributes: dict[str, str] = {}  # e.g. {"size": "1.5L", "flavor": "Original"}
    weight_kg: float | None = Field(default=None, ge=0)
    length_cm: float | None = Field(default=None, ge=0)
    width_cm: float | None = Field(default=None, ge=0)
    height_cm: float | None = Field(default=None, ge=0)
    unit: str = ""  # leave empty to use the product's unit
    status: ActiveStatus = ActiveStatus.ACTIVE


class PriceIn(CamelModel):
    """One price tier (section 9). Example tiers: 1-9 pcs = 120, 10-49 = 110, 50+ = 100."""

    variant_id: str | None = None  # None = applies to the product (all variants without their own price)
    price_type: PriceType = PriceType.WHOLESALE
    price: float = Field(ge=0)
    currency: str = Field(default="PHP", min_length=3, max_length=3)
    minimum_quantity: int = Field(default=1, ge=1)
    maximum_quantity: int | None = Field(default=None, ge=1)
    customer_type: BusinessType | None = None  # None = every buyer; e.g. RETAILER = retailers only
    effective_from: datetime.date | None = None
    effective_until: datetime.date | None = None
    status: ActiveStatus = ActiveStatus.ACTIVE

    @model_validator(mode="after")
    def check_ranges(self):
        if self.maximum_quantity and self.maximum_quantity < self.minimum_quantity:
            raise ValueError("maximum quantity must be at least the minimum quantity")
        check_date_order(self.effective_from, self.effective_until, "effective until must be after effective from")
        return self
