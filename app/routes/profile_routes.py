"""Legal info, contacts, locations, social links, certifications, documents, and verification requests."""

from fastapi import APIRouter, Depends, status
from google.cloud.firestore import Client

from app.controllers import (
    contact_controller,
    location_controller,
    settings_controller,
    trust_controller,
    verification_controller,
)
from app.core.firebase import get_db
from app.dependencies.business_access import BusinessAccess, get_business_access
from app.models.network import VerificationRequest
from app.models.profile import BusinessDocument, Certification, Contact, Location, SocialLink
from app.models.settings import LegalInfo
from app.schemas.contact import ContactIn
from app.schemas.legal import LegalIn
from app.schemas.location import LocationIn
from app.schemas.trust import CertificationIn, DocumentIn, SocialLinkIn, VerificationRequestIn

router = APIRouter(prefix="/businesses/{business_id}", tags=["Business profile"])

# ---- Legal & registration -------------------------------------------------------------------


@router.get("/legal", response_model=LegalInfo)
def get_legal(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return settings_controller.get_legal(db, access.business_id)


@router.put("/legal", response_model=LegalInfo)
def save_legal(legal_in: LegalIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return settings_controller.save_legal(db, access, legal_in)


# ---- Contacts -----------------------------------------------------------------------------


@router.get("/contacts", response_model=list[Contact])
def list_contacts(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return contact_controller.list_contacts(db, access.business_id)


@router.post("/contacts", response_model=Contact, status_code=status.HTTP_201_CREATED)
def create_contact(contact_in: ContactIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return contact_controller.create_contact(db, access, contact_in)


@router.put("/contacts/{contact_id}", response_model=Contact)
def update_contact(
    contact_id: str, contact_in: ContactIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return contact_controller.update_contact(db, access, contact_id, contact_in)


@router.delete("/contacts/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(contact_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    contact_controller.delete_contact(db, access, contact_id)


# ---- Locations (with opening hours) -------------------------------------------------------


@router.get("/locations", response_model=list[Location])
def list_locations(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return location_controller.list_locations(db, access.business_id)


@router.post("/locations", response_model=Location, status_code=status.HTTP_201_CREATED)
def create_location(
    location_in: LocationIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return location_controller.create_location(db, access, location_in)


@router.put("/locations/{location_id}", response_model=Location)
def update_location(
    location_id: str, location_in: LocationIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return location_controller.update_location(db, access, location_id, location_in)


@router.delete("/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_location(location_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    location_controller.delete_location(db, access, location_id)


# ---- Social links ---------------------------------------------------------------------------


@router.get("/social-links", response_model=list[SocialLink])
def list_social_links(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return trust_controller.list_social_links(db, access.business_id)


@router.post("/social-links", response_model=SocialLink, status_code=status.HTTP_201_CREATED)
def create_social_link(link_in: SocialLinkIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return trust_controller.create_social_link(db, access, link_in)


@router.put("/social-links/{link_id}", response_model=SocialLink)
def update_social_link(
    link_id: str, link_in: SocialLinkIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return trust_controller.update_social_link(db, access, link_id, link_in)


@router.delete("/social-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_social_link(link_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    trust_controller.delete_social_link(db, access, link_id)


# ---- Certifications -------------------------------------------------------------------------


@router.get("/certifications", response_model=list[Certification])
def list_certifications(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return trust_controller.list_certifications(db, access.business_id)


@router.post("/certifications", response_model=Certification, status_code=status.HTTP_201_CREATED)
def create_certification(
    cert_in: CertificationIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return trust_controller.create_certification(db, access, cert_in)


@router.put("/certifications/{cert_id}", response_model=Certification)
def update_certification(
    cert_id: str, cert_in: CertificationIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return trust_controller.update_certification(db, access, cert_id, cert_in)


@router.delete("/certifications/{cert_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_certification(cert_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    trust_controller.delete_certification(db, access, cert_id)


# ---- Documents ------------------------------------------------------------------------------


@router.get("/documents", response_model=list[BusinessDocument])
def list_documents(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return trust_controller.list_documents(db, access.business_id)


@router.post("/documents", response_model=BusinessDocument, status_code=status.HTTP_201_CREATED)
def create_document(
    document_in: DocumentIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return trust_controller.create_document(db, access, document_in)


@router.put("/documents/{document_id}", response_model=BusinessDocument)
def update_document(
    document_id: str, document_in: DocumentIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return trust_controller.update_document(db, access, document_id, document_in)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    trust_controller.delete_document(db, access, document_id)


# ---- Verification requests ------------------------------------------------------------------


@router.get("/verifications", response_model=list[VerificationRequest])
def list_verification_requests(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return verification_controller.list_requests_for_business(db, access.business_id)


@router.post("/verifications", response_model=VerificationRequest, status_code=status.HTTP_201_CREATED)
def submit_verification_request(
    request_in: VerificationRequestIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return verification_controller.submit_request(db, access, request_in)
