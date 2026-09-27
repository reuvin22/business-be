"""Delivery, payments, returns, and supplier capabilities."""

from fastapi import APIRouter, Depends, status
from google.cloud.firestore import Client

from app.controllers import delivery_zone_controller, payment_method_controller, settings_controller
from app.core.firebase import get_db
from app.dependencies.business_access import BusinessAccess, get_business_access
from app.models.profile import DeliveryZone, PaymentMethod
from app.models.settings import DeliverySettings, PaymentTerms, ReturnPolicy, SupplierProfile
from app.schemas.delivery import DeliverySettingsIn, DeliveryZoneIn
from app.schemas.payment import PaymentMethodIn, PaymentTermsIn
from app.schemas.policies import ReturnPolicyIn, SupplierProfileIn

router = APIRouter(prefix="/businesses/{business_id}", tags=["Commerce settings"])

# ---- Delivery -----------------------------------------------------------------------------


@router.get("/delivery", response_model=DeliverySettings)
def get_delivery(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return settings_controller.get_delivery(db, access.business_id)


@router.put("/delivery", response_model=DeliverySettings)
def save_delivery(
    delivery_in: DeliverySettingsIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return settings_controller.save_delivery(db, access, delivery_in)


@router.get("/delivery-zones", response_model=list[DeliveryZone])
def list_delivery_zones(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return delivery_zone_controller.list_delivery_zones(db, access.business_id)


@router.post("/delivery-zones", response_model=DeliveryZone, status_code=status.HTTP_201_CREATED)
def create_delivery_zone(
    zone_in: DeliveryZoneIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return delivery_zone_controller.create_delivery_zone(db, access, zone_in)


@router.put("/delivery-zones/{zone_id}", response_model=DeliveryZone)
def update_delivery_zone(
    zone_id: str, zone_in: DeliveryZoneIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return delivery_zone_controller.update_delivery_zone(db, access, zone_id, zone_in)


@router.delete("/delivery-zones/{zone_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_delivery_zone(zone_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    delivery_zone_controller.delete_delivery_zone(db, access, zone_id)


# ---- Payment methods (private) and payment terms ------------------------------------------


@router.get("/payment-methods", response_model=list[PaymentMethod])
def list_payment_methods(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return payment_method_controller.list_payment_methods(db, access.business_id)


@router.post("/payment-methods", response_model=PaymentMethod, status_code=status.HTTP_201_CREATED)
def create_payment_method(
    method_in: PaymentMethodIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return payment_method_controller.create_payment_method(db, access, method_in)


@router.put("/payment-methods/{method_id}", response_model=PaymentMethod)
def update_payment_method(
    method_id: str, method_in: PaymentMethodIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return payment_method_controller.update_payment_method(db, access, method_id, method_in)


@router.delete("/payment-methods/{method_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_payment_method(method_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    payment_method_controller.delete_payment_method(db, access, method_id)


@router.get("/payment-terms", response_model=PaymentTerms)
def get_payment_terms(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return settings_controller.get_payment_terms(db, access.business_id)


@router.put("/payment-terms", response_model=PaymentTerms)
def save_payment_terms(
    terms_in: PaymentTermsIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return settings_controller.save_payment_terms(db, access, terms_in)


# ---- Return policy and supplier profile -----------------------------------------------------


@router.get("/return-policy", response_model=ReturnPolicy)
def get_return_policy(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return settings_controller.get_return_policy(db, access.business_id)


@router.put("/return-policy", response_model=ReturnPolicy)
def save_return_policy(
    policy_in: ReturnPolicyIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return settings_controller.save_return_policy(db, access, policy_in)


@router.get("/supplier-profile", response_model=SupplierProfile)
def get_supplier_profile(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return settings_controller.get_supplier_profile(db, access.business_id)


@router.put("/supplier-profile", response_model=SupplierProfile)
def save_supplier_profile(
    profile_in: SupplierProfileIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return settings_controller.save_supplier_profile(db, access, profile_in)
