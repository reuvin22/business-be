from app.schemas.base import CamelModel


class CurrentUser(CamelModel):
    """The logged-in Firebase user, read from the token the frontend sends."""

    uid: str
    email: str | None = None
    name: str | None = None
    picture: str | None = None
    is_admin: bool = False  # platform admin (see ADMIN_EMAILS in .env)
