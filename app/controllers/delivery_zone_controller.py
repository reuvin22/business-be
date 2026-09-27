from google.cloud.firestore import Client

from app.controllers import crud
from app.dependencies.business_access import BusinessAccess
from app.models.profile import DeliveryZone, delivery_zones_collection
from app.schemas.delivery import DeliveryZoneIn
from app.schemas.enums import Permission


def list_delivery_zones(db: Client, business_id: str) -> list[DeliveryZone]:
    return crud.list_documents(delivery_zones_collection(db, business_id), DeliveryZone)


def create_delivery_zone(db: Client, access: BusinessAccess, zone_in: DeliveryZoneIn) -> DeliveryZone:
    access.require(Permission.EDIT_BUSINESS)
    return crud.create_document(delivery_zones_collection(db, access.business_id), DeliveryZone, zone_in)


def update_delivery_zone(db: Client, access: BusinessAccess, zone_id: str, zone_in: DeliveryZoneIn) -> DeliveryZone:
    access.require(Permission.EDIT_BUSINESS)
    return crud.update_document(
        delivery_zones_collection(db, access.business_id), zone_id, DeliveryZone, zone_in, "Delivery zone"
    )


def delete_delivery_zone(db: Client, access: BusinessAccess, zone_id: str) -> None:
    access.require(Permission.EDIT_BUSINESS)
    crud.delete_document(delivery_zones_collection(db, access.business_id), zone_id, "Delivery zone")
