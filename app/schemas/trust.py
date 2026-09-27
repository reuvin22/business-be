"""Schemas for certifications, social links, documents, and verification (sections 18-20, 24)."""

import datetime

from pydantic import Field, model_validator

from app.schemas.base import CamelModel, UrlText, check_date_order
from app.schemas.enums import DocumentType, SocialPlatform, VerificationStatus, VerificationType


class CertificationIn(CamelModel):
    """e.g. FDA, ISO, HACCP, Halal."""

    certification_name: str = Field(min_length=1)
    issuing_organization: str = ""
    certificate_number: str = ""
    issue_date: datetime.date | None = None
    expiry_date: datetime.date | None = None
    document_url: UrlText = ""  # private: only your team and platform admins see it

    @model_validator(mode="after")
    def check_dates(self):
        check_date_order(self.issue_date, self.expiry_date, "expiry date must be after issue date")
        return self


class PublicCertification(CamelModel):
    id: str
    certification_name: str
    issuing_organization: str
    certificate_number: str
    issue_date: datetime.date | None
    expiry_date: datetime.date | None
    verification_status: VerificationStatus


class SocialLinkIn(CamelModel):
    platform: SocialPlatform
    username: str = ""
    url: UrlText = Field(min_length=1)


class DocumentIn(CamelModel):
    """A permit, certificate, ID, contract, ... Only your team and platform admins can see documents."""

    document_type: DocumentType
    file_url: UrlText = Field(min_length=1)
    file_name: str = ""
    issue_date: datetime.date | None = None
    expiry_date: datetime.date | None = None

    @model_validator(mode="after")
    def check_dates(self):
        check_date_order(self.issue_date, self.expiry_date, "expiry date must be after issue date")
        return self


class VerificationRequestIn(CamelModel):
    """Ask the platform to verify the business, attaching documents from the Documents list."""

    verification_type: VerificationType
    document_ids: list[str] = []
    notes: str = ""

    @model_validator(mode="after")
    def needs_documents(self):
        if self.verification_type != VerificationType.BASIC and not self.document_ids:
            raise ValueError("attach at least one document")
        return self


class VerificationReviewIn(CamelModel):
    """An admin's decision on a verification request."""

    status: VerificationStatus
    rejection_reason: str = ""

    @model_validator(mode="after")
    def check_decision(self):
        allowed = {
            VerificationStatus.VERIFIED,
            VerificationStatus.REJECTED,
            VerificationStatus.SUSPENDED,
            VerificationStatus.EXPIRED,
        }
        if self.status not in allowed:
            raise ValueError("status must be VERIFIED, REJECTED, SUSPENDED, or EXPIRED")
        if self.status == VerificationStatus.REJECTED and not self.rejection_reason:
            raise ValueError("give a reason when rejecting")
        return self


class StatusIn(CamelModel):
    """An admin setting the verification status of one certification or document."""

    status: VerificationStatus
