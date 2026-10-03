"""Orders between businesses. {business_id} is the buyer or the seller."""

from typing import Literal

from fastapi import APIRouter, Depends, status
from google.cloud.firestore import Client

from app.controllers import order_controller, review_controller
from app.core.firebase import get_db
from app.dependencies.business_access import BusinessAccess, get_business_access
from app.models.network import Review
from app.models.trade import Order
from app.schemas.network import ReviewIn
from app.schemas.order import OrderChargesIn, OrderIn, OrderStatusIn, PaymentProofIn, PaymentStatusIn, Quote
from app.schemas.upload import OpenedFile
from app.schemas.views import OrderView

router = APIRouter(prefix="/businesses/{business_id}/orders", tags=["Orders"])


@router.get("", response_model=list[Order])
def list_orders(
    side: Literal["buying", "selling"] | None = None,
    db: Client = Depends(get_db),
    access: BusinessAccess = Depends(get_business_access),
):
    return order_controller.list_orders(db, access, side)


@router.post("/quote", response_model=Quote)
def quote_order(order_in: OrderIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    """Prices an order without placing it. Check `problems` before placing."""
    return order_controller.quote_order(db, access, order_in)


@router.post("", response_model=Order, status_code=status.HTTP_201_CREATED)
def create_order(order_in: OrderIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return order_controller.create_order(db, access, order_in)


@router.get("/{order_id}", response_model=OrderView)
def get_order(order_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return order_controller.get_order_view(db, access, order_id)


@router.post("/{order_id}/status", response_model=Order)
def change_order_status(
    order_id: str, status_in: OrderStatusIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return order_controller.change_order_status(db, access, order_id, status_in)


@router.post("/{order_id}/payment-status", response_model=Order)
def change_payment_status(
    order_id: str, payment_in: PaymentStatusIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return order_controller.change_payment_status(db, access, order_id, payment_in)


@router.post("/{order_id}/payment-proof", response_model=Order)
def add_payment_proof(
    order_id: str, proof_in: PaymentProofIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    """The buyer attaches proof of payment: files uploaded with kind=proof (private)."""
    return order_controller.add_payment_proof(db, access, order_id, proof_in)


@router.get("/{order_id}/payment-proof", response_model=OpenedFile)
def open_payment_proof(
    order_id: str, ref: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    """A 5-minute link to one proof of payment (both businesses of the order may open it)."""
    return OpenedFile(url=order_controller.open_payment_proof(db, access, order_id, ref))


@router.put("/{order_id}/charges", response_model=Order)
def change_order_charges(
    order_id: str, charges_in: OrderChargesIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return order_controller.change_order_charges(db, access, order_id, charges_in)


@router.post("/{order_id}/review", response_model=Review, status_code=status.HTTP_201_CREATED)
def review_order(
    order_id: str, review_in: ReviewIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return review_controller.create_review(db, access, order_id, review_in)
