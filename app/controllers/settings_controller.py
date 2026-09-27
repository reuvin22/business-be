"""Details that exist once per business: legal info, delivery settings, payment terms,
return policy, and supplier profile."""

from google.cloud.firestore import Client

from app.controllers import crud
from app.dependencies.business_access import BusinessAccess
from app.models.business import business_document
from app.models.settings import (
    DeliverySettings,
    LegalInfo,
    PaymentTerms,
    ReturnPolicy,
    SupplierProfile,
    settings_document,
)
from app.schemas.delivery import DeliverySettingsIn
from app.schemas.enums import Permission
from app.schemas.legal import LegalIn
from app.schemas.payment import PaymentTermsIn
from app.schemas.policies import ReturnPolicyIn, SupplierProfileIn

# ---- Legal & registration (private: team only) ---------------------------------------------


def get_legal(db: Client, business_id: str) -> LegalInfo:
    return crud.get_single_document(settings_document(db, business_id, "legal"), LegalInfo)


def save_legal(db: Client, access: BusinessAccess, legal_in: LegalIn) -> LegalInfo:
    access.require(Permission.EDIT_BUSINESS)
    return crud.save_single_document(settings_document(db, access.business_id, "legal"), LegalInfo, legal_in)


# ---- Delivery settings (public) ----------------------------------------------------------


def get_delivery(db: Client, business_id: str) -> DeliverySettings:
    return crud.get_single_document(settings_document(db, business_id, "delivery"), DeliverySettings)


def save_delivery(db: Client, access: BusinessAccess, delivery_in: DeliverySettingsIn) -> DeliverySettings:
    access.require(Permission.EDIT_BUSINESS)
    return crud.save_single_document(settings_document(db, access.business_id, "delivery"), DeliverySettings, delivery_in)


# ---- Payment terms (public) --------------------------------------------------------------


def get_payment_terms(db: Client, business_id: str) -> PaymentTerms:
    return crud.get_single_document(settings_document(db, business_id, "paymentTerms"), PaymentTerms)


def save_payment_terms(db: Client, access: BusinessAccess, terms_in: PaymentTermsIn) -> PaymentTerms:
    access.require(Permission.MANAGE_PAYMENTS)
    return crud.save_single_document(settings_document(db, access.business_id, "paymentTerms"), PaymentTerms, terms_in)


# ---- Return policy (public) --------------------------------------------------------------


def get_return_policy(db: Client, business_id: str) -> ReturnPolicy:
    return crud.get_single_document(settings_document(db, business_id, "returnPolicy"), ReturnPolicy)


def save_return_policy(db: Client, access: BusinessAccess, policy_in: ReturnPolicyIn) -> ReturnPolicy:
    access.require(Permission.EDIT_BUSINESS)
    return crud.save_single_document(settings_document(db, access.business_id, "returnPolicy"), ReturnPolicy, policy_in)


# ---- Supplier profile (public) -----------------------------------------------------------


def get_supplier_profile(db: Client, business_id: str) -> SupplierProfile:
    return crud.get_single_document(settings_document(db, business_id, "supplierProfile"), SupplierProfile)


def save_supplier_profile(db: Client, access: BusinessAccess, profile_in: SupplierProfileIn) -> SupplierProfile:
    access.require(Permission.EDIT_BUSINESS)
    profile = crud.save_single_document(
        settings_document(db, access.business_id, "supplierProfile"), SupplierProfile, profile_in
    )
    # Copied onto the business so the directory can filter by capability without extra reads
    business_document(db, access.business_id).update({"capabilities": profile_in.enabled_capabilities()})
    return profile
