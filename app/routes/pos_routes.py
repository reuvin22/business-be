"""The selling app (my-business-pos), and the seller accounts the main app manages."""

import datetime

from fastapi import APIRouter, Depends, status
from google.cloud.firestore import Client

from app.controllers import pos_controller, seller_controller
from app.core.firebase import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.business_access import BusinessAccess, get_business_access, get_pos_access
from app.models.inventory import InventoryItem, StockMovement
from app.models.member import Member
from app.models.pos import Receipt
from app.schemas.pos import (
    CheckoutIn,
    PosBusiness,
    PosContext,
    PosProduct,
    SellerCreateIn,
    SellerPasswordIn,
    SellerUpdateIn,
    StockChangeIn,
    VoidIn,
)
from app.schemas.user import CurrentUser

router = APIRouter(tags=["Selling app"])

# ---- Seller accounts (used by the main app's Team page) -------------------------------------


@router.get("/businesses/{business_id}/sellers", response_model=list[Member])
def list_sellers(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return seller_controller.list_sellers(db, access)


@router.post("/businesses/{business_id}/sellers", response_model=Member, status_code=status.HTTP_201_CREATED)
def create_seller(
    seller_in: SellerCreateIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return seller_controller.create_seller(db, access, seller_in)


@router.put("/businesses/{business_id}/sellers/{user_id}", response_model=Member)
def update_seller(
    user_id: str,
    seller_in: SellerUpdateIn,
    db: Client = Depends(get_db),
    access: BusinessAccess = Depends(get_business_access),
):
    return seller_controller.update_seller(db, access, user_id, seller_in)


@router.put("/businesses/{business_id}/sellers/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
def set_seller_password(
    user_id: str,
    password_in: SellerPasswordIn,
    db: Client = Depends(get_db),
    access: BusinessAccess = Depends(get_business_access),
):
    seller_controller.set_password(db, access, user_id, password_in)


@router.delete("/businesses/{business_id}/sellers/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_seller(user_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    seller_controller.remove_seller(db, access, user_id)


# ---- The selling app ------------------------------------------------------------------------


@router.get("/pos/businesses", response_model=list[PosBusiness])
def list_pos_businesses(db: Client = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    """Businesses the logged-in user can sell for."""
    return pos_controller.list_pos_businesses(db, user)


@router.get("/businesses/{business_id}/pos/context", response_model=PosContext)
def get_context(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)):
    return pos_controller.get_context(db, access)


@router.get("/businesses/{business_id}/pos/catalog", response_model=list[PosProduct])
def get_catalog(
    date: datetime.date | None = None, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)
):
    """Products for sale with today's prices. Send ?date= (the seller's local date) for date-limited prices."""
    return pos_controller.get_catalog(db, access, date or datetime.date.today())


@router.get("/businesses/{business_id}/pos/stock", response_model=list[InventoryItem])
def list_stock(location_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)):
    return pos_controller.list_stock(db, access, location_id)


@router.get("/businesses/{business_id}/pos/stock-history", response_model=list[StockMovement])
def list_stock_history(
    location_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)
):
    return pos_controller.list_stock_history(db, access, location_id)


@router.post("/businesses/{business_id}/pos/stock-changes", response_model=InventoryItem)
def change_stock(
    change_in: StockChangeIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)
):
    return pos_controller.change_stock(db, access, change_in)


@router.post("/businesses/{business_id}/pos/checkouts", response_model=Receipt, status_code=status.HTTP_201_CREATED)
def checkout(checkout_in: CheckoutIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)):
    return pos_controller.checkout(db, access, checkout_in)


@router.get("/businesses/{business_id}/pos/receipts", response_model=list[Receipt])
def list_receipts(
    date: datetime.date,
    location_id: str | None = None,
    db: Client = Depends(get_db),
    access: BusinessAccess = Depends(get_pos_access),
):
    return pos_controller.list_receipts(db, access, date, location_id)


@router.post("/businesses/{business_id}/pos/receipts/{receipt_id}/void", response_model=Receipt)
def void_receipt(
    receipt_id: str, void_in: VoidIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)
):
    return pos_controller.void_receipt(db, access, receipt_id, void_in)


@router.delete("/businesses/{business_id}/pos/receipts/{receipt_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_receipt(receipt_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_pos_access)):
    """Managers only: removes the receipt and its sales for good (stock goes back unless it was voided)."""
    pos_controller.delete_receipt(db, access, receipt_id)
