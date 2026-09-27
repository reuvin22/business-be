from google.cloud.firestore import Client

from app.controllers import crud
from app.dependencies.business_access import BusinessAccess
from app.models.profile import PaymentMethod, payment_methods_collection
from app.schemas.enums import Permission, PaymentType
from app.schemas.payment import PaymentMethodIn


def list_payment_methods(db: Client, business_id: str) -> list[PaymentMethod]:
    return crud.list_documents(payment_methods_collection(db, business_id), PaymentMethod)


def list_accepted_payment_types(db: Client, business_id: str) -> list[PaymentType]:
    """The public part: which kinds of payment the business accepts, without account details."""
    types = {method.payment_type for method in list_payment_methods(db, business_id) if method.is_active}
    return sorted(types)


def create_payment_method(db: Client, access: BusinessAccess, method_in: PaymentMethodIn) -> PaymentMethod:
    access.require(Permission.MANAGE_PAYMENTS)
    return crud.create_document(payment_methods_collection(db, access.business_id), PaymentMethod, method_in)


def update_payment_method(
    db: Client, access: BusinessAccess, method_id: str, method_in: PaymentMethodIn
) -> PaymentMethod:
    access.require(Permission.MANAGE_PAYMENTS)
    return crud.update_document(
        payment_methods_collection(db, access.business_id), method_id, PaymentMethod, method_in, "Payment method"
    )


def delete_payment_method(db: Client, access: BusinessAccess, method_id: str) -> None:
    access.require(Permission.MANAGE_PAYMENTS)
    crud.delete_document(payment_methods_collection(db, access.business_id), method_id, "Payment method")
