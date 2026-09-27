from pydantic import Field

from app.schemas.base import CamelModel, EmailText
from app.schemas.enums import ContactPosition, ContactType


class ContactIn(CamelModel):
    """A person other businesses can reach, e.g. Purchasing -> Maria (section 3)."""

    user_id: str = ""  # optional: the team member's user id, if this contact has an account
    contact_type: ContactType = ContactType.REPRESENTATIVE
    first_name: str = Field(min_length=1)
    last_name: str = ""
    position: ContactPosition = ContactPosition.OTHER
    email: EmailText = ""
    phone: str = ""
    is_primary: bool = False
    show_on_profile: bool = True  # shown on the public profile to other businesses


class PublicContact(CamelModel):
    id: str
    contact_type: ContactType
    first_name: str
    last_name: str
    position: ContactPosition
    email: str
    phone: str
    is_primary: bool
    is_verified: bool
