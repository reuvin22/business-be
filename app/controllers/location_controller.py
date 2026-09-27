from google.cloud.firestore import Client, FieldFilter

from app.controllers import crud
from app.controllers.crud import bad_request
from app.dependencies.business_access import BusinessAccess
from app.models.business import business_document
from app.models.inventory import inventory_collection
from app.models.profile import Location, locations_collection
from app.schemas.enums import Permission
from app.schemas.location import LocationIn


def list_locations(db: Client, business_id: str) -> list[Location]:
    return crud.list_documents(locations_collection(db, business_id), Location)


def create_location(db: Client, access: BusinessAccess, location_in: LocationIn) -> Location:
    access.require(Permission.EDIT_BUSINESS)
    is_first = not list_locations(db, access.business_id)
    if location_in.is_primary:
        _clear_primary(db, access.business_id)

    # The first location is always the primary one
    location = crud.create_document(
        locations_collection(db, access.business_id), Location, location_in, is_primary=location_in.is_primary or is_first
    )
    _copy_primary_address_to_business(db, access.business_id)
    return location


def update_location(db: Client, access: BusinessAccess, location_id: str, location_in: LocationIn) -> Location:
    access.require(Permission.EDIT_BUSINESS)
    if location_in.is_primary:
        _clear_primary(db, access.business_id, except_id=location_id)
    location = crud.update_document(locations_collection(db, access.business_id), location_id, Location, location_in, "Location")
    _copy_primary_address_to_business(db, access.business_id)
    return location


def delete_location(db: Client, access: BusinessAccess, location_id: str) -> None:
    access.require(Permission.EDIT_BUSINESS)
    stock_here = inventory_collection(db, access.business_id).where(filter=FieldFilter("locationId", "==", location_id))
    if any(True for _ in stock_here.limit(1).stream()):
        raise bad_request("This location still has inventory records. Delete or move them first.")

    crud.delete_document(locations_collection(db, access.business_id), location_id, "Location")
    _copy_primary_address_to_business(db, access.business_id)


def _clear_primary(db: Client, business_id: str, except_id: str | None = None) -> None:
    for location in list_locations(db, business_id):
        if location.is_primary and location.id != except_id:
            locations_collection(db, business_id).document(location.id).update({"isPrimary": False})


def _copy_primary_address_to_business(db: Client, business_id: str) -> None:
    """The directory filters by city, so the primary location's city is copied onto the business."""
    locations = list_locations(db, business_id)
    primary = next((loc for loc in locations if loc.is_primary), locations[0] if locations else None)
    business_document(db, business_id).update(
        {"primaryCity": primary.city if primary else "", "primaryProvince": primary.province if primary else ""}
    )
