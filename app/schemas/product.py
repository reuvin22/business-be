import datetime

from pydantic import Field, model_validator

from app.schemas.base import CamelModel, UrlText, check_date_order
from app.schemas.enums import ActiveStatus, BusinessType, MediaType, PriceType, ProductStatus, Visibility


class ProductImage(CamelModel):
    """One photo or video of a product (the name stays "image" so products saved earlier still fit)."""

    image_url: UrlText = Field(min_length=1)
    media_type: MediaType = MediaType.IMAGE
    sort_order: int = 0
    is_primary: bool = False  # only an image can be the primary (it is the thumbnail in lists)


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
        """Sorts images and videos, and makes sure exactly one image is the primary (the first image, if none
        was chosen). Videos are never the primary, so a product with only videos has none."""
        self.images.sort(key=lambda image: image.sort_order)
        photos = [image for image in self.images if image.media_type == MediaType.IMAGE]
        primary = next((image for image in photos if image.is_primary), photos[0] if photos else None)
        for image in self.images:
            image.is_primary = image is primary
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


class VariantDraft(VariantIn):
    """A variant inside the product form.

    key: the variant's id when it already exists, or any temporary name for a new one (e.g. "new-1").
    Price tiers point to a variant by this key.
    """

    key: str = Field(min_length=1)


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


class PriceDraft(PriceIn):
    """A price tier inside the product form."""

    id: str | None = None  # the tier's id when it already exists; None = new
    variant_key: str | None = None  # which variant (its key in the form); None = the whole product


class ProductFormIn(ProductIn):
    """A product with its variants and price tiers, saved together in one step."""

    variants: list[VariantDraft] = []
    prices: list[PriceDraft] = []

    @model_validator(mode="after")
    def check_links(self):
        keys = [variant.key for variant in self.variants]
        if len(keys) != len(set(keys)):
            raise ValueError("each variant needs its own key")
        for price in self.prices:
            if price.variant_key and price.variant_key not in keys:
                raise ValueError("a price tier points to a variant that is not in the form")
        return self
