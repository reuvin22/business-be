# my-business-be

The FastAPI backend for **my-business-fe**: a B2B platform where businesses (suppliers, manufacturers, distributors, retailers, …) keep their profile and catalog, find each other in a directory, order from each other, message each other, and review each other.

- **Login:** Firebase Authentication. The frontend sends the user's ID token and the API checks it.
- **Database:** Cloud Firestore, accessed with the Firebase Admin SDK.
- **Business ≠ user:** a user can be a member of several businesses, each with a role and permissions.

## Getting started

Before the first run, create the database: Firebase Console → **Firestore Database** → **Create database**.

> **Windows:** installing Python from [python.org](https://www.python.org/downloads/) is recommended over the Microsoft Store version.
> If the server or tests stop for no reason (exit code -1 or 127), another program may be closing `python.exe`
> processes. Close other background tools and try again.

```bash
# 1. Create a virtual environment and install packages
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements-dev.txt   # the app + test tools

# 2. Settings
copy .env.example .env          # Windows  (cp on macOS / Linux)
#    - Firebase Console > Project settings > Service accounts > Generate new private key
#      Save it in this folder as firebase-service-account.json
#    - Put your own email in ADMIN_EMAILS to use the Platform admin page

# 3. Run the server (it reloads when you save a file)
fastapi dev app/main.py
```

- API: http://localhost:8000 · interactive docs: http://localhost:8000/docs
- All routes are versioned under `/api/v1` (only `/api/health` is not). The frontend reads the base URL from `VITE_API_URL`, e.g. `http://localhost:8000/api/v1`.

## Folder structure (MVC)

```
app/
├── main.py                 # Creates the app, adds CORS, registers every router under /api/v1
├── core/                   # Setup used everywhere
│   ├── config.py           #   Settings from .env
│   ├── firebase.py         #   get_db() (Firestore), verify_token(), find_user_by_email()
│   └── permissions.py      #   Default permissions for each team role
├── schemas/                # V: the JSON shapes going in and out (Pydantic)
│   ├── base.py             #   CamelModel (snake_case in Python <-> camelCase in JSON) + UrlText, EmailText, TimeText
│   ├── enums.py            #   Every fixed list of choices (business types, order statuses, ...)
│   ├── business.py, legal.py, contact.py, location.py, brand.py, category.py, product.py,
│   ├── inventory.py, delivery.py, payment.py, policies.py, trust.py, network.py, order.py, sale.py
│   ├── directory.py        #   What other businesses see (public profile, public catalog)
│   └── views.py            #   Responses with extra calculated fields (OrderView, ConversationView)
├── models/                 # M: what is stored in Firestore, and where
│   ├── base.py             #   FirestoreModel: id/createdAt/updatedAt + from_snapshot() / to_firestore()
│   ├── business.py         #   businesses/{id}
│   ├── member.py           #   businesses/{id}/members/{userId}
│   ├── settings.py         #   businesses/{id}/settings/{legal|delivery|paymentTerms|returnPolicy|supplierProfile}
│   ├── profile.py          #   contacts, locations, brands, deliveryZones, paymentMethods, certifications, socialLinks, documents
│   ├── product.py          #   products + variants + prices
│   ├── inventory.py        #   inventory (one record per product/variant per location)
│   ├── trade.py            #   orders (top-level) and walk-in sales
│   ├── network.py          #   relationships, customerPrices, reviews, conversations/messages, verificationRequests
│   └── category.py         #   categories (shared by the platform)
├── controllers/            # C: the business logic
│   ├── crud.py             #   Shared list/get/create/update/delete helpers
│   ├── pricing.py          #   Price tiers, customer prices, order rules, delivery fees (plain functions)
│   ├── order_controller.py #   Quotes, placing orders, status changes with stock reservation
│   └── ... one controller per area
├── routes/                 # URLs only. Each route checks access and calls one controller function.
└── dependencies/
    ├── auth.py             #   get_current_user (login required), require_admin
    └── business_access.py  #   get_business_access: the business in the URL + the member + their permissions
```

### How a request flows

```
Frontend ──> routes/ ──> controllers/ ──> models/ ──> Firestore
               │              │
         schemas/*In     access.require(Permission.X) → 403
         checks input    HTTPException(404/400) when something is wrong
               │
         response_model builds the JSON (camelCase)
```

Every route under `/businesses/{business_id}/...` uses `get_business_access`. Non-members get **404** (so they can't tell the business exists); members without the needed permission get **403**.

## Data in Firestore

```
businesses/{businessId}                 identity + memberUids, verification, rating, capabilities, primaryCity
  members/{userId}                      role, permissions, status
  settings/legal | delivery | paymentTerms | returnPolicy | supplierProfile
  contacts, locations (with operatingHours), socialLinks, certifications, documents
  brands, products/{id} (images, specifications, orderRules inside)
      variants/{id}, prices/{id}
  inventory/{productId__variantId__locationId}
  deliveryZones, paymentMethods, customerPrices, sales
  reviews/{orderId}
categories/{id}                          shared tree, managed by platform admins
orders/{id}                              buyer + seller (businessIds), items copied in
relationships/{id}                       two businesses (businessIds)
conversations/{id}/messages/{id}
verificationRequests/{id}
```

Design choices:

- **Small detail tables live inside their parent** (opening hours in a location; images, specs, and order rules in a product). One read gets everything.
- **Only simple queries** (one `==` or `array_contains` filter; sorting happens in Python), so you never have to create Firestore indexes. When a list gets very large (e.g. thousands of directory entries), switch to a search service.
- **Transactions** protect stock: walk-in sales, confirming/shipping/cancelling orders, and stock adjustments can't oversell.
- **Names and prices are copied** onto orders and sales, so history stays correct after a product changes.
- **Files are links** for now (logos, product images, documents). Real uploads need Firebase Storage (Blaze plan).

## Main flows

| Flow | How it works |
| ---- | ------------ |
| Team | The creator is OWNER. Add members by email (they must have signed up). Roles give default permissions (`app/core/permissions.py`); you can change them per member. |
| Pricing | Price tiers per product/variant (quantity ranges, optional buyer type, dates). A private customer price for a buyer beats the tiers. The lowest applicable price wins. |
| Ordering | Buyer asks for a quote (`POST /orders/quote`), then places the order. The server works out every price, checks MOQ / multiples / min value, delivery options and zones, payment method and terms. |
| Order status | PENDING → (seller) CONFIRMED (reserves stock at a location) → SHIPPED (takes stock out) → DELIVERED → (buyer) COMPLETED. Seller can REJECT a pending order or CANCEL a confirmed one (releases stock); buyer can CANCEL while pending. |
| Payments | Buyers see only the payment *types* publicly. After the seller confirms, the buyer sees the account details of the chosen method. |
| Reviews | Only the buyer of a COMPLETED order can review, once per order, with separate 1–5 scores. The seller can reply; admins can hide. |
| Relationships | "Acme is our SUPPLIER": the other side accepts or declines; either side can end it. |
| Verification | Business uploads document links and requests a level (Basic, Identity, Business, Supplier). A platform admin approves or rejects; the badge says exactly what was checked. |

## Tests

Tests never touch your real Firestore. They use the **Firestore emulator** (needs [Java 11+](https://adoptium.net/) and Node.js).

```bash
# Terminal 1
npx firebase-tools emulators:start --only firestore --project demo-my-business

# Terminal 2
set FIRESTORE_EMULATOR_HOST=127.0.0.1:8080       # Windows cmd
# $env:FIRESTORE_EMULATOR_HOST="127.0.0.1:8080"  # PowerShell
pytest
```

Without the emulator, `pytest` runs the validation and pricing tests and skips the rest.

## Deploy to Render (Docker)

The `Dockerfile` builds a small production image (no tests, no secrets). Render passes the port in `$PORT`.

1. Push this folder to GitHub (the key file and `.env` are ignored, so they are not uploaded).
2. Render → **New → Web Service** → pick the repo. Runtime: **Docker**. If the repo holds both projects, set **Root Directory** to `my-business-be`.
3. **Environment → Secret Files**: add a file named `firebase-service-account.json` with the contents of your service account key.
   Render puts it at `/etc/secrets/firebase-service-account.json`.
4. **Environment → Environment Variables**:

   | Key | Value |
   | --- | ----- |
   | `FIREBASE_CREDENTIALS_PATH` | `/etc/secrets/firebase-service-account.json` |
   | `CORS_ORIGINS` | your frontend URL, e.g. `https://my-business.onrender.com` (comma-separate several) |
   | `ADMIN_EMAILS` | your email |

5. **Health Check Path**: `/api/health`.
6. In the frontend, set `VITE_API_URL=https://<your-api>.onrender.com/api/v1` and rebuild it.

Test the image locally (with Docker Desktop running):

```bash
docker build -t my-business-be .
docker run -p 8000:8000 --env-file .env -e FIREBASE_CREDENTIALS_PATH=/secrets/key.json -v "%cd%/firebase-service-account.json:/secrets/key.json:ro" my-business-be
```

On Render's free plan the service sleeps after ~15 minutes without traffic; the first request after that takes a while.

## Common changes

**Add a field to a form.** Add it to the `...In` schema in `app/schemas/` (with a default so old documents still load), then to the form in the frontend (`src/forms/definitions.ts`) and the type in `src/api/types.ts`.

**Add a new list for a business** (e.g. `expenses`):

1. `app/schemas/expense.py`: `ExpenseIn` with the fields and validation.
2. `app/models/profile.py` (or a new file): `class Expense(ExpenseIn, FirestoreModel)` and `expenses_collection()`.
3. `app/controllers/expense_controller.py`: use `crud.list_documents / create_document / ...`, and `access.require(Permission....)` before changes.
4. `app/routes/...`: add the routes with `access: BusinessAccess = Depends(get_business_access)`, and register a new router in `app/main.py`.
5. Frontend: `listResource<Expense>('expenses')` in `src/api/resources.ts` and a `<ResourceSection>` on a page.

**Add a permission.** Add it to `Permission` in `app/schemas/enums.py`, to `ROLE_PERMISSIONS` in `app/core/permissions.py`, and to `PERMISSIONS` / `ROLE_PERMISSIONS` in the frontend's `src/constants/options.ts`.

## Security notes

- Never commit `.env` or the service account key (both are in `.gitignore`). Move `my-business-fe/my-business.json` into this folder as `firebase-service-account.json` and update `.env`.
- `firestore.rules` blocks all direct browser access, because only this API (Admin SDK) should touch the data. Deploy it with `npx firebase-tools deploy --only firestore:rules --project <your-project-id>`.
- Documents, legal info, payment account numbers, cost prices, and customer prices are never returned by the public directory endpoints.
