from google.cloud.firestore import Client, CollectionReference

from app.models.base import FirestoreModel
from app.models.business import business_subcollection
from app.schemas.product import PriceIn, ProductIn, VariantIn

# Firestore locations:
#   businesses/{businessId}/products/{productId}
#   businesses/{businessId}/products/{productId}/variants/{variantId}
#   businesses/{businessId}/products/{productId}/prices/{priceId}


class Product(ProductIn, FirestoreModel):
    pass


class Variant(VariantIn, FirestoreModel):
    product_id: str = ""


class Price(PriceIn, FirestoreModel):
    product_id: str = ""


def products_collection(db: Client, business_id: str) -> CollectionReference:
    return business_subcollection(db, business_id, "products")


def variants_collection(db: Client, business_id: str, product_id: str) -> CollectionReference:
    return products_collection(db, business_id).document(product_id).collection("variants")


def prices_collection(db: Client, business_id: str, product_id: str) -> CollectionReference:
    return products_collection(db, business_id).document(product_id).collection("prices")
