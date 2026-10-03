"""Every list of fixed choices used by the API.

The frontend has the same lists in src/constants/options.ts. Keep them in sync.
StrEnum values are saved in Firestore and sent as JSON as plain text, e.g. "SUPPLIER".
"""

from enum import StrEnum

# ---- Business identity ------------------------------------------------------------------


class BusinessType(StrEnum):
    MANUFACTURER = "MANUFACTURER"
    SUPPLIER = "SUPPLIER"
    DISTRIBUTOR = "DISTRIBUTOR"
    WHOLESALER = "WHOLESALER"
    RETAILER = "RETAILER"
    IMPORTER = "IMPORTER"
    EXPORTER = "EXPORTER"
    SERVICE_PROVIDER = "SERVICE_PROVIDER"
    BRAND_OWNER = "BRAND_OWNER"
    FARMER_PRODUCER = "FARMER_PRODUCER"
    OTHER = "OTHER"


class BusinessSize(StrEnum):
    MICRO = "MICRO"  # 1-9 employees
    SMALL = "SMALL"  # 10-99
    MEDIUM = "MEDIUM"  # 100-199
    LARGE = "LARGE"  # 200+


class BusinessStatus(StrEnum):
    ACTIVE = "ACTIVE"  # shown in the directory
    INACTIVE = "INACTIVE"  # hidden from the directory
    CLOSED = "CLOSED"


# ---- Verification ------------------------------------------------------------------------


class VerificationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class VerificationType(StrEnum):
    """What an admin actually checked. Only show a label the platform really verified."""

    BASIC = "BASIC"  # contact details confirmed
    IDENTITY = "IDENTITY"  # owner's government ID checked
    BUSINESS = "BUSINESS"  # registration documents (DTI/SEC, permit, BIR) checked
    SUPPLIER = "SUPPLIER"  # supplier capabilities / certifications checked


class RegistrationType(StrEnum):
    DTI = "DTI"
    SEC = "SEC"
    CDA = "CDA"  # cooperatives
    OTHER = "OTHER"


class DocumentType(StrEnum):
    BUSINESS_PERMIT = "BUSINESS_PERMIT"
    DTI_CERTIFICATE = "DTI_CERTIFICATE"
    SEC_CERTIFICATE = "SEC_CERTIFICATE"
    BIR_DOCUMENT = "BIR_DOCUMENT"
    TAX_DOCUMENT = "TAX_DOCUMENT"
    LICENSE = "LICENSE"
    CERTIFICATION = "CERTIFICATION"
    ID = "ID"
    CONTRACT = "CONTRACT"
    OTHER = "OTHER"


# ---- People --------------------------------------------------------------------------------


class ContactType(StrEnum):
    OWNER = "OWNER"
    REPRESENTATIVE = "REPRESENTATIVE"
    EMPLOYEE = "EMPLOYEE"
    AGENT = "AGENT"


class ContactPosition(StrEnum):
    OWNER = "OWNER"
    MANAGER = "MANAGER"
    SALES = "SALES"
    PURCHASING = "PURCHASING"
    ACCOUNTING = "ACCOUNTING"
    CUSTOMER_SERVICE = "CUSTOMER_SERVICE"
    LOGISTICS = "LOGISTICS"
    ADMIN = "ADMIN"
    OTHER = "OTHER"


class MemberRole(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    SALES = "SALES"
    PURCHASING = "PURCHASING"
    ACCOUNTING = "ACCOUNTING"
    WAREHOUSE = "WAREHOUSE"
    STAFF = "STAFF"
    SELLER = "SELLER"  # selling-app account created by the business (see seller_controller.py)


class MemberStatus(StrEnum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Permission(StrEnum):
    """What a member is allowed to change. Every member can view their business."""

    EDIT_BUSINESS = "business.edit"  # profile, legal, locations, contacts, documents, verification
    MANAGE_MEMBERS = "members.manage"
    MANAGE_PRODUCTS = "products.manage"  # products, variants, prices, brands, customer prices
    MANAGE_INVENTORY = "inventory.manage"  # stock levels and walk-in sales
    MANAGE_SALES_ORDERS = "orders.sell"  # confirm, ship, and charge orders from customers
    PLACE_ORDERS = "orders.buy"  # buy from suppliers
    MANAGE_PAYMENTS = "payments.manage"  # payment methods and payment terms
    SEND_MESSAGES = "messages.send"
    MANAGE_RELATIONSHIPS = "relationships.manage"
    WRITE_REVIEWS = "reviews.write"
    USE_POS = "pos.use"  # sell and receive stock in the selling app (my-business-pos)


# ---- Locations -------------------------------------------------------------------------------


class LocationType(StrEnum):
    HEAD_OFFICE = "HEAD_OFFICE"
    BRANCH = "BRANCH"
    WAREHOUSE = "WAREHOUSE"
    FACTORY = "FACTORY"
    STORE = "STORE"
    DISTRIBUTION_CENTER = "DISTRIBUTION_CENTER"
    PICKUP_POINT = "PICKUP_POINT"


class DayOfWeek(StrEnum):
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"


# ---- Catalog -----------------------------------------------------------------------------------


class ActiveStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ActivityCategory(StrEnum):
    """The groups the activity history can be filtered by."""

    PRODUCTS = "PRODUCTS"
    MESSAGES = "MESSAGES"
    CONNECTIONS = "CONNECTIONS"
    ORDERS = "ORDERS"
    SALES = "SALES"  # voided or deleted receipts, and stock taken out at the counter (so managers see them)


class MediaType(StrEnum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"
    DOCUMENT = "DOCUMENT"  # a PDF (e.g. the full return policy)


class ProductStatus(StrEnum):
    ACTIVE = "ACTIVE"
    DRAFT = "DRAFT"
    ARCHIVED = "ARCHIVED"


class Visibility(StrEnum):
    PUBLIC = "PUBLIC"  # shown to other businesses in the directory
    PRIVATE = "PRIVATE"  # only your team sees it


class PriceType(StrEnum):
    RETAIL = "RETAIL"
    WHOLESALE = "WHOLESALE"
    DISTRIBUTOR = "DISTRIBUTOR"
    BULK = "BULK"
    SPECIAL = "SPECIAL"


class StockMovementType(StrEnum):
    """Why the quantity on hand changed (one line in the stock history)."""

    STOCK_ADDED = "STOCK_ADDED"  # a new stock record was created
    ADJUSTMENT = "ADJUSTMENT"  # someone added or removed stock (delivery received, damaged, ...)
    CORRECTION = "CORRECTION"  # someone typed in a new quantity
    SALE = "SALE"  # walk-in sale
    SALE_UNDONE = "SALE_UNDONE"  # a walk-in sale was undone, stock put back
    ORDER_SHIPPED = "ORDER_SHIPPED"  # an order left the location (orders accepted before stock was taken on accept)
    ORDER_ACCEPTED = "ORDER_ACCEPTED"  # the seller accepted an order: its quantities were taken out
    ORDER_CANCELLED = "ORDER_CANCELLED"  # an accepted order was cancelled: its quantities were put back
    RECORD_REMOVED = "RECORD_REMOVED"  # the stock record was deleted


class StockStatus(StrEnum):
    IN_STOCK = "IN_STOCK"
    LOW_STOCK = "LOW_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"


# ---- Logistics & payments ------------------------------------------------------------------------


class DeliveryMethod(StrEnum):
    """How a business delivers (shown on its profile)."""

    OWN_DELIVERY = "OWN_DELIVERY"
    COURIER = "COURIER"
    FREIGHT = "FREIGHT"
    OTHER = "OTHER"


class FulfillmentMethod(StrEnum):
    """How a buyer receives one order."""

    DELIVERY = "DELIVERY"
    PICKUP = "PICKUP"
    SHIPPING = "SHIPPING"


class PaymentType(StrEnum):
    """The kind of payment. Which bank, e-wallet, or card goes in the method's provider (e.g. E_WALLET + "GCash")."""

    CASH = "CASH"
    COD = "COD"
    BANK_TRANSFER = "BANK_TRANSFER"
    E_WALLET = "E_WALLET"
    CARD = "CARD"
    ONLINE_PAYMENT = "ONLINE_PAYMENT"
    CHEQUE = "CHEQUE"
    CREDIT_TERMS = "CREDIT_TERMS"
    # Older kinds that named the provider. Still read (old methods and orders); saved as the new kinds
    # (see LEGACY_PAYMENT_TYPES in app/schemas/payment.py)
    GCASH = "GCASH"
    MAYA = "MAYA"
    CREDIT_CARD = "CREDIT_CARD"
    DEBIT_CARD = "DEBIT_CARD"


class PaymentTerm(StrEnum):
    PREPAID = "PREPAID"
    COD = "COD"
    DOWN_PAYMENT_50 = "DOWN_PAYMENT_50"
    NET_7 = "NET_7"
    NET_15 = "NET_15"
    NET_30 = "NET_30"
    NET_60 = "NET_60"


class RefundMethod(StrEnum):
    ORIGINAL_PAYMENT = "ORIGINAL_PAYMENT"
    CASH = "CASH"
    BANK_TRANSFER = "BANK_TRANSFER"
    STORE_CREDIT = "STORE_CREDIT"
    REPLACEMENT_ONLY = "REPLACEMENT_ONLY"


class SocialPlatform(StrEnum):
    FACEBOOK = "FACEBOOK"
    INSTAGRAM = "INSTAGRAM"
    TIKTOK = "TIKTOK"
    LINKEDIN = "LINKEDIN"
    YOUTUBE = "YOUTUBE"
    X = "X"
    WEBSITE = "WEBSITE"
    SHOPEE = "SHOPEE"
    LAZADA = "LAZADA"
    OTHER = "OTHER"


# ---- Orders --------------------------------------------------------------------------------------


class OrderStatus(StrEnum):
    PENDING = "PENDING"  # placed by the buyer, waiting for the seller
    CONFIRMED = "CONFIRMED"  # seller accepted; stock is reserved
    SHIPPED = "SHIPPED"  # left the seller (or picked up); stock is deducted
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"  # buyer confirmed receipt; can now be reviewed
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"  # seller declined


class PaymentStatus(StrEnum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class DeliveryStatus(StrEnum):
    NOT_SHIPPED = "NOT_SHIPPED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


# ---- Network -------------------------------------------------------------------------------------


class RelationshipType(StrEnum):
    """What the *related* business is to you: "Acme is my SUPPLIER"."""

    SUPPLIER = "SUPPLIER"
    CUSTOMER = "CUSTOMER"
    DISTRIBUTOR = "DISTRIBUTOR"
    RESELLER = "RESELLER"
    PARTNER = "PARTNER"
    MANUFACTURER = "MANUFACTURER"
    AUTHORIZED_DEALER = "AUTHORIZED_DEALER"


class RelationshipStatus(StrEnum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DECLINED = "DECLINED"
    ENDED = "ENDED"


class ReviewStatus(StrEnum):
    PUBLISHED = "PUBLISHED"
    HIDDEN = "HIDDEN"


class ConversationStatus(StrEnum):
    OPEN = "OPEN"
    ARCHIVED = "ARCHIVED"


class PosPaymentType(StrEnum):
    """How a walk-in customer paid at the counter (selling app)."""

    CASH = "CASH"
    E_WALLET = "E_WALLET"
    # No longer offered for new sales (see CheckoutIn); kept so older receipts still load
    CARD = "CARD"
    BANK_TRANSFER = "BANK_TRANSFER"


class PosTemplate(StrEnum):
    """How the selling app looks and what it asks, for the kind of business. Products, prices, stock,
    and receipts work the same in every template."""

    DEFAULT = "DEFAULT"  # retail: product tiles with photos and stock
    GROCERY = "GROCERY"  # a compact list made for scanning
    RESTAURANT = "RESTAURANT"  # a menu by category; dine-in (table number), take-out, delivery
    COFFEE_SHOP = "COFFEE_SHOP"  # a menu by category; sizes on each drink; the customer's name
    CUSTOM = "CUSTOM"  # the business switches each feature on or off itself (PosSettingsIn.custom)


class OrderType(StrEnum):
    """Restaurants and coffee shops: how the order is served."""

    DINE_IN = "DINE_IN"
    TAKE_OUT = "TAKE_OUT"
    DELIVERY = "DELIVERY"


class OnlinePaymentStatus(StrEnum):
    """An online payment at the counter (Xendit), from the QR code to the receipt."""

    PENDING = "PENDING"  # waiting for the customer to pay
    COMPLETED = "COMPLETED"  # paid, and the sale is saved (receipt_id)
    PAID_NOT_SAVED = "PAID_NOT_SAVED"  # paid, but the sale could not be saved (e.g. stock ran out): check it
    EXPIRED = "EXPIRED"
    CANCELED = "CANCELED"


class ReceiptStatus(StrEnum):
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"  # undone; the stock was put back
