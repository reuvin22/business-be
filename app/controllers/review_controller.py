"""Reviews (section 21). A buyer can review a seller once per COMPLETED order."""

from google.cloud.firestore import Client

from app.controllers import crud
from app.controllers.crud import bad_request
from app.controllers.order_controller import get_order
from app.dependencies.business_access import BusinessAccess
from app.models.business import business_document
from app.models.network import Review, reviews_collection
from app.models.trade import orders_collection
from app.schemas.enums import OrderStatus, Permission, ReviewStatus
from app.schemas.network import ReviewIn, ReviewResponseIn
from app.utils.helpers import current_time_ms


def list_reviews(db: Client, business_id: str, include_hidden: bool = False) -> list[Review]:
    reviews = crud.list_documents(reviews_collection(db, business_id), Review)
    if not include_hidden:
        reviews = [r for r in reviews if r.status == ReviewStatus.PUBLISHED]
    return sorted(reviews, key=lambda r: r.created_at, reverse=True)


def create_review(db: Client, access: BusinessAccess, order_id: str, review_in: ReviewIn) -> Review:
    """The buyer reviews the seller of one of its completed orders."""
    access.require(Permission.WRITE_REVIEWS)
    order = get_order(db, access, order_id)
    if order.buyer_business_id != access.business_id:
        raise bad_request("Only the buyer can review an order")
    if order.order_status != OrderStatus.COMPLETED:
        raise bad_request("You can review an order after marking it completed")
    if order.reviewed:
        raise bad_request("You already reviewed this order")

    scores = review_in.ratings.given_scores()
    now = current_time_ms()
    review = Review(
        id=order.id,  # one review per order
        reviewer_business_id=access.business_id,
        reviewer_business_name=access.business.business_name,
        order_id=order.id,
        ratings=review_in.ratings,
        rating=round(sum(scores) / len(scores), 2),
        review=review_in.review,
        created_at=now,
        updated_at=now,
    )

    batch = db.batch()
    batch.set(reviews_collection(db, order.seller_business_id).document(order.id), review.to_firestore())
    batch.update(orders_collection(db).document(order.id), {"reviewed": True})
    batch.commit()

    refresh_rating(db, order.seller_business_id)
    return review


def respond_to_review(db: Client, access: BusinessAccess, review_id: str, response_in: ReviewResponseIn) -> Review:
    """The seller replies to a review about them."""
    access.require(Permission.EDIT_BUSINESS)
    review = crud.get_document(reviews_collection(db, access.business_id), review_id, Review, "Review")
    review.response = response_in.response
    review.responded_at = current_time_ms()
    reviews_collection(db, access.business_id).document(review_id).update(
        {"response": review.response, "respondedAt": review.responded_at}
    )
    return review


def set_review_status(db: Client, business_id: str, review_id: str, status: ReviewStatus) -> Review:
    """Platform admins can hide a review that breaks the rules."""
    review = crud.get_document(reviews_collection(db, business_id), review_id, Review, "Review")
    reviews_collection(db, business_id).document(review_id).update({"status": status.value})
    review.status = status
    refresh_rating(db, business_id)
    return review


def refresh_rating(db: Client, business_id: str) -> None:
    """Recalculates the business's average rating from its published reviews."""
    reviews = list_reviews(db, business_id)
    average = round(sum(r.rating for r in reviews) / len(reviews), 2) if reviews else 0
    business_document(db, business_id).update({"ratingAverage": average, "ratingCount": len(reviews)})
