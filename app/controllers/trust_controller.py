"""Certifications, social links, and documents."""

from google.cloud.firestore import Client

from app.controllers import crud
from app.core import cache
from app.dependencies.business_access import BusinessAccess
from app.models.profile import (
    BusinessDocument,
    Certification,
    SocialLink,
    certifications_collection,
    documents_collection,
    social_links_collection,
)
from app.schemas.enums import Permission, VerificationStatus
from app.schemas.trust import CertificationIn, DocumentIn, SocialLinkIn
from app.utils.helpers import current_time_ms

# ---- Certifications ------------------------------------------------------------------------


def list_certifications(db: Client, business_id: str) -> list[Certification]:
    return crud.list_documents(certifications_collection(db, business_id), Certification)


def create_certification(db: Client, access: BusinessAccess, cert_in: CertificationIn) -> Certification:
    access.require(Permission.EDIT_BUSINESS)
    return crud.create_document(certifications_collection(db, access.business_id), Certification, cert_in)


def update_certification(db: Client, access: BusinessAccess, cert_id: str, cert_in: CertificationIn) -> Certification:
    access.require(Permission.EDIT_BUSINESS)
    # Changing a certificate means it has to be checked again
    return crud.update_document(
        certifications_collection(db, access.business_id),
        cert_id,
        Certification,
        cert_in,
        "Certification",
        verification_status=VerificationStatus.UNVERIFIED,
    )


def delete_certification(db: Client, access: BusinessAccess, cert_id: str) -> None:
    access.require(Permission.EDIT_BUSINESS)
    crud.delete_document(certifications_collection(db, access.business_id), cert_id, "Certification", Certification)


def set_certification_status(db: Client, business_id: str, cert_id: str, status: VerificationStatus) -> Certification:
    """Platform admins only (see admin routes)."""
    cert = crud.get_document(certifications_collection(db, business_id), cert_id, Certification, "Certification")
    certifications_collection(db, business_id).document(cert_id).update({"verificationStatus": status.value})
    cache.bump(cache.business_scope(business_id))
    cert.verification_status = status
    return cert


# ---- Social links --------------------------------------------------------------------------


def list_social_links(db: Client, business_id: str) -> list[SocialLink]:
    return crud.list_documents(social_links_collection(db, business_id), SocialLink)


def create_social_link(db: Client, access: BusinessAccess, link_in: SocialLinkIn) -> SocialLink:
    access.require(Permission.EDIT_BUSINESS)
    return crud.create_document(social_links_collection(db, access.business_id), SocialLink, link_in)


def update_social_link(db: Client, access: BusinessAccess, link_id: str, link_in: SocialLinkIn) -> SocialLink:
    access.require(Permission.EDIT_BUSINESS)
    return crud.update_document(
        social_links_collection(db, access.business_id), link_id, SocialLink, link_in, "Social link", verified=False
    )


def delete_social_link(db: Client, access: BusinessAccess, link_id: str) -> None:
    access.require(Permission.EDIT_BUSINESS)
    crud.delete_document(social_links_collection(db, access.business_id), link_id, "Social link")


# ---- Documents (private: team and platform admins only) ------------------------------------


def list_documents(db: Client, business_id: str) -> list[BusinessDocument]:
    return crud.list_documents(documents_collection(db, business_id), BusinessDocument)


def create_document(db: Client, access: BusinessAccess, document_in: DocumentIn) -> BusinessDocument:
    access.require(Permission.EDIT_BUSINESS)
    return crud.create_document(documents_collection(db, access.business_id), BusinessDocument, document_in)


def update_document(db: Client, access: BusinessAccess, document_id: str, document_in: DocumentIn) -> BusinessDocument:
    access.require(Permission.EDIT_BUSINESS)
    return crud.update_document(
        documents_collection(db, access.business_id),
        document_id,
        BusinessDocument,
        document_in,
        "Document",
        verification_status=VerificationStatus.UNVERIFIED,
        verified_at=None,
    )


def delete_document(db: Client, access: BusinessAccess, document_id: str) -> None:
    access.require(Permission.EDIT_BUSINESS)
    crud.delete_document(documents_collection(db, access.business_id), document_id, "Document", BusinessDocument)


def set_document_status(db: Client, business_id: str, document_id: str, status: VerificationStatus) -> None:
    """Used by platform admins when they review a verification request."""
    verified_at = current_time_ms() if status == VerificationStatus.VERIFIED else None
    doc_ref = documents_collection(db, business_id).document(document_id)
    if doc_ref.get().exists:
        doc_ref.update({"verificationStatus": status.value, "verifiedAt": verified_at})
        cache.bump(cache.business_scope(business_id))
