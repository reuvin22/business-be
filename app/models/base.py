from google.cloud.firestore import DocumentSnapshot

from app.schemas.base import CamelModel


class FirestoreModel(CamelModel):
    """Base for everything saved in Firestore.

    A model is "what the user filled in" (its ...In schema) plus the fields below.
    Example:  class Contact(ContactIn, FirestoreModel)
    """

    id: str = ""  # the Firestore document id (not saved inside the document itself)
    created_at: int = 0  # milliseconds since 1970, like Date.now() in JavaScript
    updated_at: int = 0

    @classmethod
    def from_snapshot(cls, snapshot: DocumentSnapshot):
        """Builds the model from a document read from Firestore."""
        return cls.model_validate({**snapshot.to_dict(), "id": snapshot.id})

    def to_firestore(self) -> dict:
        """The fields to save in Firestore: camelCase names, enums and dates as text."""
        return self.model_dump(mode="json", by_alias=True, exclude={"id"})
