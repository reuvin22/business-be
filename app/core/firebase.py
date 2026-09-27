import json
from pathlib import Path

import firebase_admin
from firebase_admin import auth, credentials, firestore
from google.cloud.firestore import Client

from app.core.config import settings


def load_credentials() -> credentials.Certificate:
    """Reads the service account key from FIREBASE_CREDENTIALS_JSON, or else from the file at
    FIREBASE_CREDENTIALS_PATH. Fails with a clear message (shown in the server logs) when neither works."""
    if settings.firebase_credentials_json.strip():
        try:
            return credentials.Certificate(json.loads(settings.firebase_credentials_json))
        except (json.JSONDecodeError, ValueError) as error:
            raise RuntimeError(f"FIREBASE_CREDENTIALS_JSON is not a valid service account key: {error}") from error

    path = Path(settings.firebase_credentials_path)
    if not path.is_file():
        raise RuntimeError(
            f"Firebase key file not found at '{path.resolve()}'. "
            "Set FIREBASE_CREDENTIALS_PATH to the key file, or put the key's JSON in FIREBASE_CREDENTIALS_JSON."
        )
    return credentials.Certificate(str(path))


def get_firebase_app() -> firebase_admin.App:
    """Starts the Firebase Admin SDK the first time it is needed, then reuses it."""
    try:
        return firebase_admin.get_app()
    except ValueError:
        return firebase_admin.initialize_app(load_credentials())


def get_db() -> Client:
    """The Firestore database. Add `db: Client = Depends(get_db)` to a route to use it."""
    return firestore.client(app=get_firebase_app())


def verify_token(id_token: str) -> dict | None:
    """Checks a Firebase ID token from the frontend.

    Returns the token's details (uid, email, name, ...) or None when the token is invalid or expired.
    """
    try:
        return auth.verify_id_token(id_token, app=get_firebase_app())
    except (ValueError, auth.InvalidIdTokenError):
        return None


def find_user_by_email(email: str) -> dict | None:
    """Looks up a Firebase account by email. Returns {uid, email, display_name} or None."""
    try:
        user = auth.get_user_by_email(email, app=get_firebase_app())
    except auth.UserNotFoundError:
        return None
    return {"uid": user.uid, "email": user.email or email, "display_name": user.display_name or ""}
