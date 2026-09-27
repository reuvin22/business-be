from app.schemas.base import CamelModel, EmailText
from app.schemas.enums import MemberRole, MemberStatus, Permission


class MemberAddIn(CamelModel):
    """Add someone to the team. They must already have an account (signed up once)."""

    email: EmailText
    role: MemberRole
    # Leave empty to use the default permissions for the role (see app/core/permissions.py)
    permissions: list[Permission] | None = None


class MemberUpdateIn(CamelModel):
    role: MemberRole
    permissions: list[Permission]
    status: MemberStatus = MemberStatus.ACTIVE
