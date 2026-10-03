"""The selling app (my-business-pos): sell at the counter, receive stock, and today's receipts.

It works on the main business's own products and stock, so every sale here takes the quantity
out of the same inventory the main app shows, and writes the same stock history.
Both apps listen to the inventory in Firestore, so they see each other's changes right away.
"""

import datetime
from dataclasses import dataclass

from fastapi import HTTPException
from google.cloud import firestore
from google.cloud.firestore import Client, DocumentReference, FieldFilter, Transaction

from app.controllers import activity_controller, crud, settings_controller
from app.controllers.category_controller import list_categories
from app.controllers.crud import bad_request, forbidden, not_found
from app.controllers.inventory_controller import (
    StockNames,
    add_stock_record,
    apply_adjustment,
    calculate_stock,
    list_movements,
    new_movement,
)
from app.controllers.pricing import is_current
from app.controllers.product_controller import get_product, list_all_prices, list_all_variants, list_prices, list_products
from app.core import cache, xendit
from app.core.config import settings
from app.dependencies.business_access import BusinessAccess, load_access
from app.models.business import Business, businesses_collection
from app.models.inventory import InventoryItem, StockMovement, inventory_collection, inventory_document
from app.models.member import Member, members_collection
from app.models.pos import (
    OnlinePayment,
    OnlinePaymentView,
    Receipt,
    ReceiptLine,
    online_payments_collection,
    receipts_collection,
)
from app.models.product import Price, Product, Variant, variants_collection
from app.models.profile import Location, locations_collection
from app.models.trade import Sale, sales_collection
from app.schemas.enums import (
    ActivityCategory,
    ActiveStatus,
    MemberRole,
    MemberStatus,
    OnlinePaymentStatus,
    Permission,
    PosPaymentType,
    PosTemplate,
    PriceType,
    ProductStatus,
    ReceiptStatus,
    StockMovementType,
)
from app.schemas.inventory import InventoryAdjustIn, InventoryIn
from app.schemas.pos import (
    CheckoutIn,
    PosBusiness,
    PosContext,
    PosLocation,
    PosPrice,
    PosProduct,
    PosVariant,
    StockChangeIn,
    VoidIn,
)
from app.schemas.user import CurrentUser
from app.utils.helpers import current_time_ms
from app.utils.parallel import run_parallel

# Sellers may void their own receipts for this long; managers can void any receipt
# A seller may only void their own sale this soon after it (e.g. a mistake at the till). Later, a manager must.
SELLER_VOID_WINDOW_MS = 15 * 60 * 1000
# How far the sale date (the till's local date) may be from the server's date: time zones, not backdating
MAX_DATE_DRIFT_DAYS = 1
# "All dates" in the receipts list shows this many of the newest receipts
ALL_DATES_LIMIT = 500


# ---- Starting the app -----------------------------------------------------------------------


def list_pos_businesses(db: Client, user: CurrentUser) -> list[PosBusiness]:
    """Businesses the user can sell for: as a seller, or as a member with the 'pos.use' permission."""

    def read() -> list[Business]:
        businesses = businesses_collection(db)
        as_seller, as_member = run_parallel(
            lambda: list(businesses.where(filter=FieldFilter("sellerUids", "array_contains", user.uid)).stream()),
            lambda: list(businesses.where(filter=FieldFilter("memberUids", "array_contains", user.uid)).stream()),
        )
        found = {snapshot.id: Business.from_snapshot(snapshot) for snapshot in [*as_seller, *as_member]}
        members = run_parallel(
            *[lambda b=b: crud.read_fresh(members_collection(db, b).document(user.uid), Member) for b in found]
        )
        usable = [
            business
            for business, member in zip(found.values(), members, strict=True)
            if member is not None and member.status == MemberStatus.ACTIVE and _can_sell(member)
        ]
        return sorted(usable, key=lambda business: business.business_name.lower())

    businesses = cache.cached_models(cache.user_scope(user.uid), "pos-businesses", Business, read)
    return [_pos_business(business) for business in businesses]


def get_context(db: Client, access: BusinessAccess) -> PosContext:
    locations = crud.list_documents(locations_collection(db, access.business_id), Location)
    if access.member.location_id:
        locations = [location for location in locations if location.id == access.member.location_id]
    return PosContext(
        business=_pos_business(access.business),
        seller_name=access.member.display_name or access.user.name or access.user.email or "",
        role=access.member.role,
        can_void_any=access.can(Permission.MANAGE_INVENTORY),
        online_payments=settings.xendit_configured,
        **_template(settings_controller.get_pos_settings(db, access.business_id)),
        locations=[PosLocation(id=location.id, location_name=location.location_name) for location in locations],
    )


def _template(pos_settings) -> dict:
    """The template for the till; the business's own switches come along only when it uses them."""
    custom = pos_settings.template == PosTemplate.CUSTOM
    return {"template": pos_settings.template, "custom": pos_settings.custom if custom else None}


def get_catalog(db: Client, access: BusinessAccess, today: datetime.date) -> list[PosProduct]:
    return catalog_for(db, access.business, today)


def catalog_for(db: Client, business: Business, today: datetime.date) -> list[PosProduct]:
    """Active products with their variants and today's counter prices.

    The whole catalog is cached as one entry (per day, since prices can start or end on a date), so
    opening the selling app is one cache read instead of one per product. It is part of the business's
    cache, so changing a product, variant, price, or the business itself makes it outdated."""
    catalog = cache.cached_models(
        cache.business_scope(business.id),
        f"pos-catalog:{today.isoformat()}",
        PosProduct,
        lambda: _build_catalog(db, business, today),
    )
    # Category names are shared by every business (and cached on their own): added here, so a renamed
    # category shows at once without rebuilding every catalog
    names = {category.id: category.category_name for category in list_categories(db)}
    for product in catalog:
        product.category_name = names.get(product.category_id or "", "")
    return catalog


def _build_catalog(db: Client, business: Business, today: datetime.date) -> list[PosProduct]:
    # One after the other: each of these already reads its products in parallel
    products = list_products(db, business.id)
    variants = list_all_variants(db, business.id)
    prices = list_all_prices(db, business.id)
    currency = business.currency
    catalog = []
    for product in products:
        if product.status != ProductStatus.ACTIVE:
            continue
        tiers = counter_tiers([p for p in prices if p.product_id == product.id], currency, today)
        catalog.append(
            PosProduct(
                id=product.id,
                product_name=product.product_name,
                sku=product.sku,
                barcode=product.barcode,
                unit=product.unit,
                image_url=next((image.image_url for image in product.images if image.is_primary), ""),
                category_id=product.category_id,
                variants=[
                    PosVariant(id=v.id, variant_name=v.variant_name, sku=v.sku, barcode=v.barcode, unit=v.unit)
                    for v in variants
                    if v.product_id == product.id and v.status == ActiveStatus.ACTIVE
                ],
                prices=[
                    PosPrice(
                        variant_id=tier.variant_id,
                        price=tier.price,
                        minimum_quantity=tier.minimum_quantity,
                        maximum_quantity=tier.maximum_quantity,
                    )
                    for tier in tiers
                ],
            )
        )
    return sorted(catalog, key=lambda product: product.product_name.lower())


def counter_tiers(prices: list[Price], currency: str, today: datetime.date) -> list[Price]:
    """The price tiers that apply to a walk-in customer today.

    Tiers for everyone win over tiers for one kind of buyer (e.g. retailers only), but when a product
    only has the latter, those are used: a walk-in customer can still buy it. Then, if the product
    has RETAIL tiers, only those are used; otherwise every tier counts."""
    usable = [
        p
        for p in prices
        if p.status == ActiveStatus.ACTIVE
        and p.currency == currency
        and is_current(p.effective_from, p.effective_until, today)
    ]
    for_everyone = [p for p in usable if p.customer_type is None]
    usable = for_everyone or usable
    retail = [p for p in usable if p.price_type == PriceType.RETAIL]
    return retail or usable


def counter_unit_price(tiers: list[Price], variant_id: str | None, quantity: int) -> float | None:
    """The price per unit at the counter, or None when the product has no price at all.

    Like the order price (the variant's own tiers first, lowest fitting tier wins), except that
    buying MORE than the biggest tier's "to quantity" keeps that tier's price instead of having none."""
    variant_tiers = [t for t in tiers if variant_id and t.variant_id == variant_id]
    tiers = variant_tiers or [t for t in tiers if t.variant_id is None]

    fitting = [
        t.price
        for t in tiers
        if t.minimum_quantity <= quantity and (t.maximum_quantity is None or quantity <= t.maximum_quantity)
    ]
    if fitting:
        return min(fitting)

    started = [t for t in tiers if t.minimum_quantity <= quantity]
    if not started:
        return None
    biggest = max(t.minimum_quantity for t in started)
    return min(t.price for t in started if t.minimum_quantity == biggest)


# ---- Stock ----------------------------------------------------------------------------------


def list_stock(db: Client, access: BusinessAccess, location_id: str) -> list[InventoryItem]:
    """Stock at one location. The app normally listens to Firestore instead; this is the fallback
    (asked every few seconds), so it is cached; every sale or stock change makes it outdated."""
    _get_location(db, access, location_id)

    def read() -> list[InventoryItem]:
        query = inventory_collection(db, access.business_id).where(filter=FieldFilter("locationId", "==", location_id))
        return [InventoryItem.from_snapshot(snapshot) for snapshot in query.stream()]

    return cache.cached_models(cache.stock_scope(access.business_id), f"pos-stock:{location_id}", InventoryItem, read)


def list_stock_history(db: Client, access: BusinessAccess, location_id: str) -> list[StockMovement]:
    _get_location(db, access, location_id)
    return list_movements(db, access.business_id, location_id=location_id, limit=100)


def change_stock(db: Client, access: BusinessAccess, change_in: StockChangeIn) -> InventoryItem:
    """Adds stock that arrived, or takes out damaged / expired stock, at the seller's store."""
    location = _get_location(db, access, change_in.location_id)
    product = get_product(db, access.business_id, change_in.product_id)
    variant = _get_variant(db, access.business_id, product, change_in.variant_id)

    doc_ref = inventory_document(db, access.business_id, product.id, change_in.variant_id, location.id)
    if not doc_ref.get().exists:
        if change_in.change < 0:
            raise bad_request("There is no stock of this product here to take out")
        new_record = InventoryIn(
            product_id=product.id, variant_id=change_in.variant_id, location_id=location.id, quantity=change_in.change
        )
        return add_stock_record(db, access, new_record, note=change_in.note)

    names = StockNames(product.product_name, variant.variant_name if variant else "", location.location_name)
    stock = apply_adjustment(db, access, doc_ref, names, InventoryAdjustIn(change=change_in.change, note=change_in.note))
    if change_in.change < 0:  # stock taken out at the counter: the managers are told
        name = f"{product.product_name} {variant.variant_name if variant else ''}".strip()
        activity_controller.record(
            db,
            access.business_id,
            ActivityCategory.SALES,
            "stock.removed",
            f"{-change_in.change:g} {name} taken out at {location.location_name}",
            by=access,
            detail=change_in.note,
        )
    return stock


def _record_sale_change(db: Client, access: BusinessAccess, action: str, title: str, receipt: Receipt, reason: str = "") -> None:
    """Tells the team (activity history and the bell) that a sale was undone, so voids are never silent."""
    total = f"{access.business.currency} {receipt.total:,.2f}"
    activity_controller.record(
        db,
        access.business_id,
        ActivityCategory.SALES,
        action,
        f"{title} ({total}, sold by {receipt.seller_name or 'a seller'})",
        by=access,
        detail=reason,
    )


# ---- Selling --------------------------------------------------------------------------------


@dataclass
class _Line:
    """One line of a checkout while it is being saved."""

    receipt_line: ReceiptLine
    sale: Sale
    stock_ref: DocumentReference


def checkout(
    db: Client,
    access: BusinessAccess,
    checkout_in: CheckoutIn,
    *,
    receipt_id: str | None = None,
    payment_reference: str = "",
    paid_online: bool = False,
) -> Receipt:
    """Sells everything in the cart at once: works out the prices and the total, takes the stock
    out, and saves the receipt, its sales, and the stock history. All or nothing.

    receipt_id: a fixed id (online payments use the payment's id). Saving the same id twice
    returns the receipt that is already there instead of selling again.
    paid_online: the money already arrived through Xendit (see complete_online_payment)."""
    method = checkout_in.payment_method
    if not paid_online and method != PosPaymentType.CASH:
        # Without Xendit, an e-wallet payment is confirmed by the seller (they see it on the customer's phone)
        if settings.xendit_configured or method != PosPaymentType.E_WALLET:
            raise bad_request("E-wallet, card, and bank transfer are paid online: use the QR code")

    receipt_ref = receipts_collection(db, access.business_id).document(receipt_id)
    location, lines, receipt_number, now = _price_cart(db, access, checkout_in, receipt_ref)

    total = round(sum(line.receipt_line.line_total for line in lines), 2)
    amount_paid = total if checkout_in.amount_paid is None else round(checkout_in.amount_paid, 2)
    if amount_paid < total:
        raise bad_request(f"The amount paid is less than the total ({total:,.2f})")
    if checkout_in.payment_method != PosPaymentType.CASH and amount_paid != total:
        raise bad_request("Only cash payments can have change")

    receipt = Receipt(
        id=receipt_ref.id,
        receipt_number=receipt_number,
        date=checkout_in.date.isoformat(),
        location_id=location.id,
        location_name=location.location_name,
        items=[line.receipt_line for line in lines],
        total=total,
        amount_paid=amount_paid,
        change_given=round(amount_paid - total, 2),
        payment_method=checkout_in.payment_method,
        payment_reference=payment_reference,
        order_type=checkout_in.order_type,
        table_number=checkout_in.table_number.strip(),
        customer_name=checkout_in.customer_name.strip(),
        note=checkout_in.note,
        seller_uid=access.user.uid,
        seller_name=_seller_name(access),
        created_at=now,
        updated_at=now,
    )
    return _save_checkout(db.transaction(), db, access, receipt_ref, receipt, lines, location)


def _price_cart(
    db: Client, access: BusinessAccess, checkout_in: CheckoutIn, receipt_ref: DocumentReference
) -> tuple[Location, list[_Line], str, int]:
    """The cart's lines with today's counter prices (nothing is saved yet)."""
    # The till sends its local date; it may differ from the server's by a time zone, but not more (no backdating)
    if abs((checkout_in.date - datetime.datetime.now(datetime.UTC).date()).days) > MAX_DATE_DRIFT_DAYS:
        raise bad_request("The sale date must be today. Check the date on this device.")
    location = _get_location(db, access, checkout_in.location_id)
    currency = access.business.currency

    # The same product twice in the cart becomes one line
    quantities: dict[tuple[str, str | None], int] = {}
    for item in checkout_in.items:
        key = (item.product_id, item.variant_id)
        quantities[key] = quantities.get(key, 0) + item.quantity

    now = current_time_ms()
    receipt_number = f"{checkout_in.date:%Y%m%d}-{receipt_ref.id[:6].upper()}"

    lines: list[_Line] = []
    for (product_id, variant_id), quantity in quantities.items():
        product = get_product(db, access.business_id, product_id)
        if product.status != ProductStatus.ACTIVE:
            raise bad_request(f"{product.product_name} is not for sale")
        variant = _get_variant(db, access.business_id, product, variant_id)
        name = f"{product.product_name} ({variant.variant_name})" if variant else product.product_name

        tiers = counter_tiers(list_prices(db, access.business_id, product_id), currency, checkout_in.date)
        unit_price = counter_unit_price(tiers, variant_id, quantity)
        if unit_price is None:
            raise bad_request(f"{name} has no selling price for this quantity")

        sale_ref = sales_collection(db, access.business_id).document()
        lines.append(
            _Line(
                receipt_line=ReceiptLine(
                    product_id=product_id,
                    variant_id=variant_id,
                    product_name=product.product_name,
                    variant_name=variant.variant_name if variant else "",
                    unit=(variant.unit if variant and variant.unit else product.unit),
                    quantity=quantity,
                    unit_price=unit_price,
                    line_total=round(unit_price * quantity, 2),
                    sale_id=sale_ref.id,
                ),
                sale=Sale(
                    id=sale_ref.id,
                    product_id=product_id,
                    variant_id=variant_id,
                    location_id=location.id,
                    quantity=quantity,
                    unit_price=unit_price,
                    date=checkout_in.date,
                    product_name=product.product_name,
                    variant_name=variant.variant_name if variant else "",
                    unit_cost=product.cost_price,
                    receipt_id=receipt_ref.id,
                    receipt_number=receipt_number,
                    created_at=now,
                    updated_at=now,
                ),
                stock_ref=inventory_document(db, access.business_id, product_id, variant_id, location.id),
            )
        )

    return location, lines, receipt_number, now


@firestore.transactional
def _save_checkout(
    transaction: Transaction,
    db: Client,
    access: BusinessAccess,
    receipt_ref: DocumentReference,
    receipt: Receipt,
    lines: list[_Line],
    location: Location,
) -> Receipt:
    # A transaction must read everything before it writes anything
    saved = receipt_ref.get(transaction=transaction)
    if saved.exists:
        return Receipt.from_snapshot(saved)  # already sold (e.g. the webhook and the till both finished it)
    snapshots = [line.stock_ref.get(transaction=transaction) for line in lines]

    writes = []
    for line, snapshot in zip(lines, snapshots, strict=True):
        name = line.receipt_line.product_name
        if not snapshot.exists:
            raise bad_request(f"{name} has no stock at {location.location_name}")
        stock = InventoryItem.from_snapshot(snapshot)
        if line.receipt_line.quantity > stock.available_quantity:
            raise bad_request(f"Only {stock.available_quantity:g} of {name} left at {location.location_name}")

        stock.quantity -= line.receipt_line.quantity
        stock.updated_at = receipt.created_at
        names = StockNames(line.receipt_line.product_name, line.receipt_line.variant_name, location.location_name)
        movement_ref, movement = new_movement(
            db,
            access.business_id,
            stock,
            names,
            StockMovementType.SALE,
            -line.receipt_line.quantity,
            access.user,
            reference_id=receipt.id,
            reference_label=receipt.receipt_number,
        )
        writes += [
            (line.stock_ref, calculate_stock(stock).to_firestore()),
            (movement_ref, movement.to_firestore()),
            (sales_collection(db, access.business_id).document(line.sale.id), line.sale.to_firestore()),
        ]

    for ref, data in writes:
        transaction.set(ref, data)
    transaction.set(receipt_ref, receipt.to_firestore())
    return receipt


def list_receipts(
    db: Client,
    access: BusinessAccess,
    date_from: datetime.date | None,
    date_to: datetime.date | None,
    location_id: str | None,
) -> list[Receipt]:
    """Receipts from date_from to date_to (the seller's days, both included), newest first.
    One day: all of it. Several days, or no dates (all of them): the newest ALL_DATES_LIMIT.
    Sellers see only their own."""
    if date_from and date_to and date_from > date_to:
        date_from, date_to = date_to, date_from
    one_day = date_from is not None and date_from == date_to
    first = date_from.isoformat() if date_from else ""
    last = date_to.isoformat() if date_to else ""

    def read() -> list[Receipt]:
        query = receipts_collection(db, access.business_id)
        if location_id:
            query = query.where(filter=FieldFilter("locationId", "==", location_id))
        newest = firestore.Query.DESCENDING
        if one_day:
            ranged = query.where(filter=FieldFilter("date", "==", first)).order_by("createdAt", direction=newest)
        else:
            ranged = query
            if first:
                ranged = ranged.where(filter=FieldFilter("date", ">=", first))
            if last:
                ranged = ranged.where(filter=FieldFilter("date", "<=", last))
            if first or last:
                ranged = ranged.order_by("date", direction=newest)  # Firestore: a range is sorted by its field first
            ranged = ranged.order_by("createdAt", direction=newest).limit(ALL_DATES_LIMIT)
        # Until the indexes are deployed (firestore.indexes.json): the store's receipts, filtered here
        return [Receipt.from_snapshot(snapshot) for snapshot in crud.stream_indexed(ranged, fallback=query)]

    key = f"receipts:{first or 'start'}:{last or 'end'}:{location_id}"
    receipts = cache.cached_models(cache.stock_scope(access.business_id), key, Receipt, read)
    receipts = [r for r in receipts if (not first or r.date >= first) and (not last or r.date <= last)]
    if access.member.role == MemberRole.SELLER:
        receipts = [r for r in receipts if r.seller_uid == access.user.uid]
    if location_id:
        receipts = [r for r in receipts if r.location_id == location_id]
    receipts = sorted(receipts, key=lambda receipt: receipt.created_at, reverse=True)
    return receipts if one_day else receipts[:ALL_DATES_LIMIT]


def void_receipt(db: Client, access: BusinessAccess, receipt_id: str, void_in: VoidIn) -> Receipt:
    """Undoes a sale: puts the stock back and removes its sales. The receipt stays, marked VOIDED."""
    receipt_ref = receipts_collection(db, access.business_id).document(receipt_id)
    receipt = crud.read_fresh(receipt_ref, Receipt)
    if receipt is None:
        raise not_found("Receipt")
    if not access.can(Permission.MANAGE_INVENTORY):
        if receipt.seller_uid != access.user.uid:
            raise forbidden("You can only void your own receipts")
        if current_time_ms() - receipt.created_at > SELLER_VOID_WINDOW_MS:
            raise forbidden("This sale is more than 15 minutes old. Ask a manager to void it.")

    voided = _void(db.transaction(), db, access, receipt_ref, _stock_refs(db, access, receipt), void_in)
    _record_sale_change(db, access, "sale.voided", f"Receipt {voided.receipt_number} voided", voided, void_in.reason)
    return voided


@firestore.transactional
def _void(
    transaction: Transaction,
    db: Client,
    access: BusinessAccess,
    receipt_ref: DocumentReference,
    stock_refs: list[DocumentReference],
    void_in: VoidIn,
) -> Receipt:
    receipt = Receipt.from_snapshot(receipt_ref.get(transaction=transaction))
    if receipt.status == ReceiptStatus.VOIDED:
        raise bad_request("This receipt is already voided")
    _put_stock_back(transaction, db, access, receipt, stock_refs, note=void_in.reason)

    now = current_time_ms()
    receipt.status = ReceiptStatus.VOIDED
    receipt.voided_at = now
    receipt.voided_by_name = _seller_name(access)
    receipt.void_reason = void_in.reason
    receipt.updated_at = now
    transaction.set(receipt_ref, receipt.to_firestore())
    return receipt


def delete_receipt(db: Client, access: BusinessAccess, receipt_id: str) -> None:
    """Deletes a receipt and its sales from the system, and puts the stock back (a voided receipt
    already did that). Managers only. The stock history keeps a line for the stock that came back."""
    access.require(Permission.MANAGE_INVENTORY)
    receipt_ref = receipts_collection(db, access.business_id).document(receipt_id)
    receipt = crud.read_fresh(receipt_ref, Receipt)
    if receipt is None:
        raise not_found("Receipt")
    _delete(db.transaction(), db, access, receipt_ref, _stock_refs(db, access, receipt))
    _record_sale_change(db, access, "sale.deleted", f"Receipt {receipt.receipt_number} deleted", receipt)


@firestore.transactional
def _delete(
    transaction: Transaction,
    db: Client,
    access: BusinessAccess,
    receipt_ref: DocumentReference,
    stock_refs: list[DocumentReference],
) -> None:
    snapshot = receipt_ref.get(transaction=transaction)
    if not snapshot.exists:
        raise not_found("Receipt")
    receipt = Receipt.from_snapshot(snapshot)
    if receipt.status == ReceiptStatus.COMPLETED:
        _put_stock_back(transaction, db, access, receipt, stock_refs, note="Receipt deleted")
    transaction.delete(receipt_ref)


def _stock_refs(db: Client, access: BusinessAccess, receipt: Receipt) -> list[DocumentReference]:
    """The stock record of each line of the receipt, in the same order."""
    return [
        inventory_document(db, access.business_id, line.product_id, line.variant_id, receipt.location_id)
        for line in receipt.items
    ]


def _put_stock_back(
    transaction: Transaction,
    db: Client,
    access: BusinessAccess,
    receipt: Receipt,
    stock_refs: list[DocumentReference],
    note: str,
) -> None:
    """Removes the receipt's sales and adds their quantities back to stock, with a history line each.
    Reads first, then writes (Firestore transactions need all reads before any write)."""
    snapshots = [ref.get(transaction=transaction) for ref in stock_refs]

    now = current_time_ms()
    for line, ref, snapshot in zip(receipt.items, stock_refs, snapshots, strict=True):
        transaction.delete(sales_collection(db, access.business_id).document(line.sale_id))
        if not snapshot.exists:
            continue  # the stock record was deleted in the meantime; nothing to put back
        stock = InventoryItem.from_snapshot(snapshot)
        stock.quantity += line.quantity
        stock.updated_at = now
        names = StockNames(line.product_name, line.variant_name, receipt.location_name)
        movement_ref, movement = new_movement(
            db,
            access.business_id,
            stock,
            names,
            StockMovementType.SALE_UNDONE,
            line.quantity,
            access.user,
            note=note,
            reference_id=receipt.id,
            reference_label=receipt.receipt_number,
        )
        transaction.set(ref, calculate_stock(stock).to_firestore())
        transaction.set(movement_ref, movement.to_firestore())


# ---- Helpers --------------------------------------------------------------------------------


def _can_sell(member: Member) -> bool:
    return member.role == MemberRole.OWNER or Permission.USE_POS in member.permissions


def _pos_business(business: Business) -> PosBusiness:
    return PosBusiness(
        id=business.id,
        business_name=business.business_name,
        business_logo=business.business_logo,
        currency=business.currency,
    )


def _seller_name(access: BusinessAccess) -> str:
    return access.member.display_name or access.user.name or access.user.email or ""


def _get_location(db: Client, access: BusinessAccess, location_id: str) -> Location:
    """The location, if this seller may work there (a seller with a store may only use that store)."""
    if access.member.location_id and location_id != access.member.location_id:
        raise forbidden("You can only sell at your own store")
    location = crud.find_document(locations_collection(db, access.business_id), location_id, Location)
    if location is None:
        raise not_found("Location")
    return location


def _get_variant(db: Client, business_id: str, product: Product, variant_id: str | None) -> Variant | None:
    if not variant_id:
        return None
    variant = crud.find_document(variants_collection(db, business_id, product.id), variant_id, Variant)
    if variant is None or variant.status != ActiveStatus.ACTIVE:
        raise bad_request(f"That variant of {product.product_name} is not for sale")
    return variant


# ---- Online payments (Xendit: e-wallet, card, bank transfer) --------------------------------


def start_online_payment(db: Client, access: BusinessAccess, checkout_in: CheckoutIn) -> OnlinePaymentView:
    """Prices the cart and makes a Xendit payment page for the exact total (shown as a QR code).
    Nothing is sold yet: the sale is saved when the payment arrives (complete_online_payment)."""
    if not settings.xendit_configured:
        raise bad_request("Online payments are not set up on the server (XENDIT_SECRET_KEY)")
    method = checkout_in.payment_method
    if method not in xendit.CHANNELS:
        raise bad_request("Choose e-wallet, card, or bank transfer")
    currency = access.business.currency
    if currency != "PHP":
        raise bad_request("Online payments are only available in PHP")

    payment_ref = online_payments_collection(db, access.business_id).document()
    # The receipt will get the payment's id, so price the cart with it
    receipt_ref = receipts_collection(db, access.business_id).document(payment_ref.id)
    location, lines, _, now = _price_cart(db, access, checkout_in, receipt_ref)
    total = round(sum(line.receipt_line.line_total for line in lines), 2)
    if total < xendit.MINIMUM_AMOUNT[method]:
        raise bad_request(f"The smallest amount for this way of paying is {xendit.MINIMUM_AMOUNT[method]:,.2f} PHP")
    # Before the customer pays: is everything still on the shelf?
    for line in lines:
        snapshot = line.stock_ref.get()
        available = InventoryItem.from_snapshot(snapshot).available_quantity if snapshot.exists else 0
        if line.receipt_line.quantity > available:
            raise bad_request(f"Only {available:g} of {line.receipt_line.product_name} left at {location.location_name}")

    session = xendit.create_session(
        reference_id=f"{access.business_id}_{payment_ref.id}",
        amount=total,
        currency=currency,
        method=method,
        description=f"{access.business.business_name}, {location.location_name}",
        customer_reference=f"walkin{payment_ref.id}",
    )
    payment = OnlinePayment(
        id=payment_ref.id,
        checkout=checkout_in.model_copy(update={"amount_paid": None}),
        payment_method=method,
        total=total,
        currency=currency,
        session_id=session.get("payment_session_id", ""),
        payment_link_url=session.get("payment_link_url", ""),
        seller_uid=access.user.uid,
        seller_name=_seller_name(access),
        created_at=now,
        updated_at=now,
    )
    payment_ref.set(payment.to_firestore())
    return OnlinePaymentView(**payment.model_dump())


def get_online_payment(db: Client, access: BusinessAccess, payment_id: str) -> OnlinePaymentView:
    """The payment now. While it is waiting, Xendit is asked, and a paid cart is sold right away."""
    payment = _find_payment(db, access, payment_id)
    if payment.status == OnlinePaymentStatus.PENDING:
        payment = sync_online_payment(db, access.business_id, payment)
    return _payment_view(db, access.business_id, payment)


def cancel_online_payment(db: Client, access: BusinessAccess, payment_id: str) -> OnlinePaymentView:
    """The customer changed their mind. If they had already paid, the sale is saved instead."""
    payment = _find_payment(db, access, payment_id)
    if payment.status == OnlinePaymentStatus.PENDING:
        xendit.cancel_session(payment.session_id)
        payment = sync_online_payment(db, access.business_id, payment)
        if payment.status == OnlinePaymentStatus.PENDING:
            payment = _set_status(db, access.business_id, payment, OnlinePaymentStatus.CANCELED)
    return _payment_view(db, access.business_id, payment)


def handle_xendit_webhook(db: Client, payload: dict) -> None:
    """Xendit says a payment page was paid or expired. We ask Xendit ourselves before selling anything,
    so only the real status counts (the webhook only tells us when to look)."""
    if payload.get("event") not in ("payment_session.completed", "payment_session.expired"):
        return
    business_id, _, payment_id = str((payload.get("data") or {}).get("reference_id", "")).partition("_")
    if not business_id or not payment_id:
        return
    snapshot = online_payments_collection(db, business_id).document(payment_id).get()
    if snapshot.exists:
        payment = OnlinePayment.from_snapshot(snapshot)
        if payment.status == OnlinePaymentStatus.PENDING:
            sync_online_payment(db, business_id, payment)


def sync_online_payment(db: Client, business_id: str, payment: OnlinePayment) -> OnlinePayment:
    """Brings the payment up to date with Xendit: sells the cart when paid, or marks it expired."""
    session = xendit.get_session(payment.session_id)
    status = session.get("status")
    if status == "COMPLETED":
        return complete_online_payment(db, business_id, payment, session.get("payment_id") or "")
    if status == "EXPIRED":
        return _set_status(db, business_id, payment, OnlinePaymentStatus.EXPIRED)
    if status == "CANCELED":
        return _set_status(db, business_id, payment, OnlinePaymentStatus.CANCELED)
    return payment


def complete_online_payment(db: Client, business_id: str, payment: OnlinePayment, payment_reference: str) -> OnlinePayment:
    """The money arrived: sell the cart as the seller who rang it up. Safe to call twice (the receipt id is fixed)."""
    try:
        seller = load_access(db, business_id, CurrentUser(uid=payment.seller_uid, name=payment.seller_name))
        receipt = checkout(
            db, seller, payment.checkout, receipt_id=payment.id, payment_reference=payment_reference, paid_online=True
        )
        payment.status = OnlinePaymentStatus.COMPLETED
        payment.receipt_id = receipt.id
    except HTTPException as error:
        # The customer paid, but e.g. the last item was sold meanwhile: someone must sort it out by hand
        payment.status = OnlinePaymentStatus.PAID_NOT_SAVED
        payment.error = f"{error.detail}. The customer has paid: record the sale by hand or refund it in Xendit."
    payment.payment_reference = payment_reference
    payment.updated_at = current_time_ms()
    online_payments_collection(db, business_id).document(payment.id).set(payment.to_firestore())
    cache.bump(cache.stock_scope(business_id))  # the stock and receipts changed (no API route did it)
    return payment


def _find_payment(db: Client, access: BusinessAccess, payment_id: str) -> OnlinePayment:
    snapshot = online_payments_collection(db, access.business_id).document(payment_id).get()
    if not snapshot.exists:
        raise not_found("Payment")
    payment = OnlinePayment.from_snapshot(snapshot)
    if payment.seller_uid != access.user.uid and not access.can(Permission.MANAGE_INVENTORY):
        raise not_found("Payment")
    return payment


def _set_status(db: Client, business_id: str, payment: OnlinePayment, status: OnlinePaymentStatus) -> OnlinePayment:
    payment.status = status
    payment.updated_at = current_time_ms()
    online_payments_collection(db, business_id).document(payment.id).update(
        {"status": status.value, "updatedAt": payment.updated_at}
    )
    return payment


def _payment_view(db: Client, business_id: str, payment: OnlinePayment) -> OnlinePaymentView:
    receipt = None
    if payment.receipt_id:
        snapshot = receipts_collection(db, business_id).document(payment.receipt_id).get()
        receipt = Receipt.from_snapshot(snapshot) if snapshot.exists else None
    return OnlinePaymentView(**payment.model_dump(), receipt=receipt)

