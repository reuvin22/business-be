from typing import ClassVar

from google.cloud.firestore import DocumentSnapshot

from app.core import crypto
from app.schemas.base import CamelModel


class FirestoreModel(CamelModel):
    """Base for everything saved in Firestore.

    A model is "what the user filled in" (its ...In schema) plus the fields below.
    Example:  class Contact(ContactIn, FirestoreModel)

    Confidential fields are listed in `encrypted_fields` (Python names). They are encrypted when saved and
    decrypted when read (see app/core/crypto.py), so the rest of the code works with plain values.
    Never list a field that a Firestore query filters or sorts on: the database only sees the encrypted text.
    """

    encrypted_fields: ClassVar[tuple[str, ...]] = ()

    id: str = ""  # the Firestore document id (not saved inside the document itself)
    created_at: int = 0  # milliseconds since 1970, like Date.now() in JavaScript
    updated_at: int = 0

    @classmethod
    def from_snapshot(cls, snapshot: DocumentSnapshot):
        """Builds the model from a document read from Firestore."""
        return cls.model_validate({**cls.decrypt_fields(snapshot.to_dict() or {}), "id": snapshot.id})

    def to_firestore(self) -> dict:
        """The fields to save in Firestore: camelCase names, enums and dates as text, confidential ones encrypted."""
        return self.encrypt_fields(self.model_dump(mode="json", by_alias=True, exclude={"id"}))

    @classmethod
    def _aliases(cls) -> list[str]:
        return [cls.model_fields[name].alias or name for name in cls.encrypted_fields]

    @classmethod
    def encrypt_fields(cls, data: dict) -> dict:
        """Encrypts the confidential fields of a Firestore dict (camelCase names), e.g. for update()."""
        return {**data, **{alias: crypto.encrypt_value(data[alias]) for alias in cls._aliases() if alias in data}}

    @classmethod
    def decrypt_fields(cls, data: dict) -> dict:
        return {**data, **{alias: crypto.decrypt_value(data[alias]) for alias in cls._aliases() if alias in data}}
