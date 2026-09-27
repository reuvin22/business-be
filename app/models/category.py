from google.cloud.firestore import Client, CollectionReference

from app.models.base import FirestoreModel
from app.schemas.category import CategoryIn

# Firestore location:  categories/{categoryId}
# Categories are shared by the whole platform and managed by platform admins.


class Category(CategoryIn, FirestoreModel):
    pass


def categories_collection(db: Client) -> CollectionReference:
    return db.collection("categories")
