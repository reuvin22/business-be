"""Brands, products, variants, price tiers, and customer-specific prices."""

from fastapi import APIRouter, Depends, status
from google.cloud.firestore import Client

from app.controllers import brand_controller, customer_price_controller, product_controller
from app.core.firebase import get_db
from app.dependencies.business_access import BusinessAccess, get_business_access
from app.models.network import CustomerPrice
from app.models.product import Price, Product, Variant
from app.models.profile import Brand
from app.schemas.brand import BrandIn
from app.schemas.network import CustomerPriceIn
from app.schemas.product import PriceIn, ProductIn, VariantIn

router = APIRouter(prefix="/businesses/{business_id}", tags=["Catalog"])

# ---- Brands -------------------------------------------------------------------------------


@router.get("/brands", response_model=list[Brand])
def list_brands(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return brand_controller.list_brands(db, access.business_id)


@router.post("/brands", response_model=Brand, status_code=status.HTTP_201_CREATED)
def create_brand(brand_in: BrandIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return brand_controller.create_brand(db, access, brand_in)


@router.put("/brands/{brand_id}", response_model=Brand)
def update_brand(
    brand_id: str, brand_in: BrandIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return brand_controller.update_brand(db, access, brand_id, brand_in)


@router.delete("/brands/{brand_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_brand(brand_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    brand_controller.delete_brand(db, access, brand_id)


# ---- Products -----------------------------------------------------------------------------


@router.get("/products", response_model=list[Product])
def list_products(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return product_controller.list_products(db, access.business_id)


@router.get("/products/{product_id}", response_model=Product)
def get_product(product_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return product_controller.get_product(db, access.business_id, product_id)


@router.post("/products", response_model=Product, status_code=status.HTTP_201_CREATED)
def create_product(product_in: ProductIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return product_controller.create_product(db, access, product_in)


@router.put("/products/{product_id}", response_model=Product)
def update_product(
    product_id: str, product_in: ProductIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return product_controller.update_product(db, access, product_id, product_in)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    product_controller.delete_product(db, access, product_id)


# ---- Variants -----------------------------------------------------------------------------


@router.get("/products/{product_id}/variants", response_model=list[Variant])
def list_variants(product_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return product_controller.list_variants(db, access.business_id, product_id)


@router.post("/products/{product_id}/variants", response_model=Variant, status_code=status.HTTP_201_CREATED)
def create_variant(
    product_id: str, variant_in: VariantIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return product_controller.create_variant(db, access, product_id, variant_in)


@router.put("/products/{product_id}/variants/{variant_id}", response_model=Variant)
def update_variant(
    product_id: str,
    variant_id: str,
    variant_in: VariantIn,
    db: Client = Depends(get_db),
    access: BusinessAccess = Depends(get_business_access),
):
    return product_controller.update_variant(db, access, product_id, variant_id, variant_in)


@router.delete("/products/{product_id}/variants/{variant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_variant(
    product_id: str, variant_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    product_controller.delete_variant(db, access, product_id, variant_id)


# ---- Price tiers --------------------------------------------------------------------------


@router.get("/products/{product_id}/prices", response_model=list[Price])
def list_prices(product_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return product_controller.list_prices(db, access.business_id, product_id)


@router.post("/products/{product_id}/prices", response_model=Price, status_code=status.HTTP_201_CREATED)
def create_price(
    product_id: str, price_in: PriceIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return product_controller.create_price(db, access, product_id, price_in)


@router.put("/products/{product_id}/prices/{price_id}", response_model=Price)
def update_price(
    product_id: str,
    price_id: str,
    price_in: PriceIn,
    db: Client = Depends(get_db),
    access: BusinessAccess = Depends(get_business_access),
):
    return product_controller.update_price(db, access, product_id, price_id, price_in)


@router.delete("/products/{product_id}/prices/{price_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_price(
    product_id: str, price_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    product_controller.delete_price(db, access, product_id, price_id)


# ---- Customer-specific prices (private) -----------------------------------------------------


@router.get("/customer-prices", response_model=list[CustomerPrice])
def list_customer_prices(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return customer_price_controller.list_customer_prices(db, access.business_id)


@router.post("/customer-prices", response_model=CustomerPrice, status_code=status.HTTP_201_CREATED)
def create_customer_price(
    price_in: CustomerPriceIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return customer_price_controller.create_customer_price(db, access, price_in)


@router.put("/customer-prices/{price_id}", response_model=CustomerPrice)
def update_customer_price(
    price_id: str, price_in: CustomerPriceIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return customer_price_controller.update_customer_price(db, access, price_id, price_in)


@router.delete("/customer-prices/{price_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer_price(price_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    customer_price_controller.delete_customer_price(db, access, price_id)
