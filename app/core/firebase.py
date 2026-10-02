import json
import os
from pathlib import Path

import firebase_admin
from firebase_admin import auth, credentials, firestore
from google.auth.credentials import AnonymousCredentials
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
        if using_emulators():
            project_id = os.environ.get("GCLOUD_PROJECT", "demo-my-business")
            return firebase_admin.initialize_app(
                _EmulatorCredential(), {"projectId": project_id, "databaseURL": _database_url(project_id)}
            )
        return firebase_admin.initialize_app(load_credentials(), {"databaseURL": settings.firebase_database_url})


def _database_url(project_id: str) -> str:
    """With the Realtime Database emulator (FIREBASE_DATABASE_EMULATOR_HOST), the Admin SDK needs
    an address that names the project's database; it then talks to the emulator."""
    host = os.environ.get("FIREBASE_DATABASE_EMULATOR_HOST")
    return f"http://{host}?ns={project_id}" if host else settings.firebase_database_url


def using_emulators() -> bool:
    """True for local development against the Firebase emulators (Auth + Firestore), which need
    no real key. Never set these two variables on a real server."""
    return bool(os.environ.get("FIREBASE_AUTH_EMULATOR_HOST") and os.environ.get("FIRESTORE_EMULATOR_HOST"))


class _EmulatorCredential(credentials.Base):
    """The emulators accept anyone, so there is nothing to sign in with."""

    def get_credential(self):
        return AnonymousCredentials()


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


# ---- Accounts made by a business (seller accounts for the selling app) --------------------


def create_account(email: str, password: str, display_name: str) -> dict:
    """Creates a Firebase email + password account. Returns {uid, email, display_name}.

    Raises auth.EmailAlreadyExistsError when the email is taken."""
    user = auth.create_user(email=email, password=password, display_name=display_name or None, app=get_firebase_app())
    return {"uid": user.uid, "email": user.email or email, "display_name": user.display_name or ""}


def set_account_password(uid: str, password: str) -> None:
    auth.update_user(uid, password=password, app=get_firebase_app())


def set_account_name(uid: str, display_name: str) -> None:
    auth.update_user(uid, display_name=display_name or None, app=get_firebase_app())
