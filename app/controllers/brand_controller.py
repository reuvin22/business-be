from google.cloud.firestore import Client, FieldFilter

from app.controllers import crud
from app.controllers.crud import bad_request
from app.dependencies.business_access import BusinessAccess
from app.models.product import products_collection
from app.models.profile import Brand, brands_collection
from app.schemas.brand import BrandIn
from app.schemas.enums import Permission


def list_brands(db: Client, business_id: str) -> list[Brand]:
    return crud.list_documents(brands_collection(db, business_id), Brand)


def create_brand(db: Client, access: BusinessAccess, brand_in: BrandIn) -> Brand:
    access.require(Permission.MANAGE_PRODUCTS)
    return crud.create_document(brands_collection(db, access.business_id), Brand, brand_in)


def update_brand(db: Client, access: BusinessAccess, brand_id: str, brand_in: BrandIn) -> Brand:
    access.require(Permission.MANAGE_PRODUCTS)
    return crud.update_document(brands_collection(db, access.business_id), brand_id, Brand, brand_in, "Brand")


def delete_brand(db: Client, access: BusinessAccess, brand_id: str) -> None:
    access.require(Permission.MANAGE_PRODUCTS)
    used_by = products_collection(db, access.business_id).where(filter=FieldFilter("brandId", "==", brand_id))
    if any(True for _ in used_by.limit(1).stream()):
        raise bad_request("Some products use this brand. Change them first, or set the brand to inactive.")
    crud.delete_document(brands_collection(db, access.business_id), brand_id, "Brand")
