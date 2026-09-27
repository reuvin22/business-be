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
        is_admin=bool(email) and email.lower() in settings.admin_email_list,
    )


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Add this to a route that only platform admins may use."""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only platform admins can do this")
    return user
