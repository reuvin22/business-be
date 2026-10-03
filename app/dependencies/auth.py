from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.firebase import verify_token
from app.schemas.user import CurrentUser

# Reads the "Authorization: Bearer <token>" header
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> CurrentUser:
    """Add this to a route to require login. Gives back the logged-in user."""
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not logged in")

    token_data = verify_token(credentials.credentials)
    if token_data is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    email = token_data.get("email")
    return CurrentUser(
        uid=token_data["uid"],
        email=email,
        name=token_data.get("name"),
        picture=token_data.get("picture"),
        is_admin=is_platform_admin(token_data),
    )


def is_platform_admin(token_data: dict) -> bool:
    """A platform admin has the `admin` custom claim (set with app/scripts/set_admin.py), or one of the
    ADMIN_EMAILS addresses AND a verified email: otherwise anyone could sign up with an admin's address."""
    if token_data.get("admin") is True:
        return True
    email = (token_data.get("email") or "").lower()
    return bool(email) and token_data.get("email_verified") is True and email in settings.admin_email_list


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Add this to a route that only platform admins may use."""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only platform admins can do this")
    return user
