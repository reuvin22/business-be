from google.cloud.firestore import Client

from app.controllers import crud
from app.controllers.crud import bad_request
from app.models.category import Category, categories_collection
from app.schemas.category import CategoryIn
from app.utils.helpers import current_time_ms

# Loaded by an admin with "Load default categories" (POST /api/categories/defaults)
DEFAULT_CATEGORIES: dict[str, list[str]] = {
    "Food": ["Beverages", "Snacks", "Canned Goods", "Baked Goods", "Frozen Food", "Condiments & Sauces"],
    "Agriculture": ["Fresh Produce", "Livestock & Poultry", "Seafood", "Rice & Grains"],
    "Health & Beauty": ["Personal Care", "Cosmetics", "Vitamins & Supplements"],
    "Household": ["Cleaning Supplies", "Kitchenware", "Home Decor"],
    "Apparel": ["Clothing", "Footwear", "Bags & Accessories"],
    "Construction": ["Building Materials", "Hardware & Tools", "Electrical"],
    "Electronics": ["Mobile & Gadgets", "Appliances", "Computer Supplies"],
    "Office & School": ["Stationery", "Office Furniture", "Printing"],
    "Packaging": ["Boxes & Cartons", "Plastic Packaging", "Labels & Stickers"],
    "Industrial": ["Chemicals", "Machinery", "Raw Materials"],
}


def list_categories(db: Client) -> list[Category]:
    return crud.list_documents(categories_collection(db), Category)


def create_category(db: Client, category_in: CategoryIn) -> Category:
    _check_parent(db, category_in.parent_category_id)
    return crud.create_document(categories_collection(db), Category, category_in)


def update_category(db: Client, category_id: str, category_in: CategoryIn) -> Category:
    if category_in.parent_category_id == category_id:
        raise bad_request("A category cannot be its own parent")
    _check_parent(db, category_in.parent_category_id)
    return crud.update_document(categories_collection(db), category_id, Category, category_in, "Category")


def delete_category(db: Client, category_id: str) -> None:
    if any(c.parent_category_id == category_id for c in list_categories(db)):
        raise bad_request("Delete or move this category's sub-categories first")
    crud.delete_document(categories_collection(db), category_id, "Category")


def load_default_categories(db: Client) -> list[Category]:
    """Adds the DEFAULT_CATEGORIES tree. Only works while there are no categories yet."""
    if list_categories(db):
        raise bad_request("Categories already exist")

    # Each timestamp is 1 ms apart so the list keeps this order
    now = current_time_ms()
    batch = db.batch()
    for parent_name, child_names in DEFAULT_CATEGORIES.items():
        parent_ref = categories_collection(db).document()
        now += 1
        parent = Category(id=parent_ref.id, category_name=parent_name, created_at=now, updated_at=now)
        batch.set(parent_ref, parent.to_firestore())
        for child_name in child_names:
            child_ref = categories_collection(db).document()
            now += 1
            child = Category(
                id=child_ref.id, category_name=child_name, parent_category_id=parent_ref.id, created_at=now, updated_at=now
            )
            batch.set(child_ref, child.to_firestore())
    batch.commit()
    return list_categories(db)


def _check_parent(db: Client, parent_id: str | None) -> None:
    if parent_id and not categories_collection(db).document(parent_id).get().exists:
        raise bad_request("Parent category not found")
