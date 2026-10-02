# my-business-be

The FastAPI backend for **SIRIS — Supplier Inventory & Retail Integration System** (frontend: **my-business-fe**): a B2B platform where businesses (suppliers, manufacturers, distributors, retailers, …) keep their profile and catalog, find each other in a directory, order from each other, message each other, and review each other.

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
conversations/{id}                       the list of chats (who, last message, unread); messages are in the Realtime Database
verificationRequests/{id}
```

Realtime Database (live chat, `database.rules.json`):
```
chatAccess/{uid}/{businessId}            who may read a business's chats (kept by the API)
chat/team/{businessId}/messages/{id}     a business's team channel
chat/market/messages/{id}                the public market channel (every signed-in user reads it)
chat/dm/{conversationId}/meta            the two businesses, when each last read the chat
chat/dm/{conversationId}/messages/{id}   messages between two businesses
live/{businessId}/activity/{id}          a business's activity, live (notifications)
notificationSeen/{uid}/{businessId}      when you last opened the notifications (the only thing browsers write)
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
| Order status | PENDING → (seller) CONFIRMED = accepted (takes the stock out at a location) → SHIPPED → DELIVERED → (buyer) COMPLETED. Seller can REJECT a pending order or CANCEL an accepted one (puts the stock back); buyer can CANCEL while pending. Both businesses are notified of every step (activity + bell). |
| Payments | Buyers see only the payment *types* publicly. After the seller confirms, the buyer sees the account details of the chosen method. |
| Reviews | Only the buyer of a COMPLETED order can review, once per order, with separate 1–5 scores. The seller can reply; admins can hide. |
| Relationships | "Acme is our SUPPLIER": the other side accepts or declines; either side can end it. |
| Verification | Business uploads document links and requests a level (Basic, Identity, Business, Supplier). A platform admin approves or rejects; the badge says exactly what was checked. |
| Selling app | See "Selling app (my-business-pos)" below. |

## Selling app (my-business-pos)

A separate web app for selling at the counter, on the main business's own products and stock.

- **Seller accounts:** in the main app, Team → Sellers → *Create seller account* (name, email, first password,
  store). The API creates the Firebase login (`app/controllers/seller_controller.py`) and adds a member with the
  `SELLER` role. Sellers can only use the selling app routes (`get_pos_access`); every other business route
  answers 403. Owners and members with the `pos.use` permission can use the selling app too.
- **Selling:** `POST /businesses/{id}/pos/checkouts`. The server works out the prices (RETAIL tiers win when a
  product has them), checks the stock, and in one transaction takes it out, saves the receipt
  (`businesses/{id}/receipts`), one Sale per line, and the stock history. Voiding a receipt puts the stock back.
- **Templates:** each business picks how its till looks (main app → Team → *Selling app template*;
  `GET/PUT /businesses/{id}/pos-settings`, saved in `settings/pos`): **Default** (retail tiles), **Grocery**
  (a list made for scanning), **Restaurant** (menu tabs; dine-in with a table number, take-out, delivery), or
  **Coffee shop** (menu tabs; sizes from variants as buttons; the customer's name). Or **Customize your own**:
  the business switches each feature on or off itself (layout, photos, category tabs, size buttons, when stock
  shows, scan-ready search, order types, table number, customer's name), starting from any built-in template. Products, prices, stock, and
  receipts work the same in all of them; receipts keep `orderType`, `tableNumber`, and `customerName`.
- **Payments:** cash or e-wallet. Card and bank transfer are no longer accepted for new sales (older receipts keep them).
- **Receipts:** `GET /businesses/{id}/pos/receipts?date=YYYY-MM-DD`, or without `date` for all dates (the newest 500).
- **Stock in / out:** `POST /businesses/{id}/pos/stock-changes` (+ delivery received, − damaged with a reason). The selling app
  no longer shows this; it only lists the recent stock changes.
- **Realtime:** both apps *listen* to `businesses/{id}/inventory` (and the selling app to `products`) straight
  from Firestore, so a sale shows on the owner's Inventory page within a second, and a delivery recorded
  in the main app shows on the till. `firestore.rules` allows active members to **read** only those two
  collections (sellers only their own store's stock); all writes still go through this API.
  **Deploy the rules** or the apps fall back to refreshing every 10–15 seconds:
  `npx firebase-tools deploy --only firestore:rules --project <your-project-id>`

## Messages (Firebase Realtime Database)

The Messages page has three kinds of chat, and new messages show up the moment they are sent:
- **# Team:** one channel per business, for its members only.
- **# Market:** one public channel. Every signed-in user can read it; members with `messages.send` post in the name
  of their business (offers, new products, what they're looking for) and can delete their business's own posts.
- **Direct messages** between two businesses. Messages from before the move to the Realtime Database are copied
  there the first time each conversation is opened.

How it works: the browser only **listens** to the Realtime Database; every message is sent through this API
(`/businesses/{id}/chat/...` and `/conversations/...`), which checks permissions and writes with the Admin SDK.
The database rules cannot read Firestore, so the API keeps `chatAccess/{uid}/{businessId}`: it is written when a
member opens Messages (`GET /businesses/{id}/chat`), and removed when they leave, are removed or made inactive, or
the business is deleted. Seller accounts never get it.

Setup (once):
1. Firebase Console → **Realtime Database** → create the database (done: `my-business-5bcad-default-rtdb`, asia-southeast1).
2. Set `FIREBASE_DATABASE_URL` on the server if it differs from the default in `app/core/config.py`, and
   `VITE_FIREBASE_DATABASE_URL` in the main app (same address).
3. **Deploy the rules** (they block everything until then, and the page says "Live updates are off"):
   `npx firebase-tools deploy --only database --project <your-project-id>`

## Places (delivery zones)

A delivery zone's area is picked level by level, each list filled from the one above (`GET /api/v1/geo/...`,
signed-in users only, `app/core/geo.py`):
- **Philippines:** the official PSGC lists (psgc.gitlab.io): region → province → city/municipality → barangay.
  Metro Manila has no provinces, so its cities come straight from the region.
- **Other countries:** CountriesNow (countriesnow.space): state/region → city.

Every list is cached in Redis for **30 days**, shared by all users (scope `geo`), and kept in the browser for 7 days,
so only the first person to open a list waits for the outside service. If a service is down, the picker says so and
the name can be typed instead. Zones now have a `country` (empty on older zones = any country); the most specific
zone wins: barangay > city > province > region > country.

## Online payments in the selling app (Xendit)

With `XENDIT_SECRET_KEY` set, the till offers **Cash, E-wallet, Card, Bank transfer**. The last three are paid
online through a Xendit Payment Session (`app/core/xendit.py`):
1. The seller taps Charge. `POST /businesses/{id}/pos/payments` prices the cart (same prices as a cash sale),
   checks the stock, and creates a Xendit payment page for the exact total. Nothing is sold yet.
2. The till shows the page as a **QR code**. The customer scans it and pays on their phone (GCash, Maya, GrabPay,
   ShopeePay, QR Ph / any card / BPI or UnionBank). For cards, the page can also be opened on the till.
3. The till asks `GET /businesses/{id}/pos/payments/{paymentId}` every 3 seconds. When Xendit says the session is
   COMPLETED, the cart is sold exactly like a cash sale (stock out, receipt, sales, stock history). The receipt
   gets the payment's id, so it is never saved twice, and Xendit's payment id is kept on it (`paymentReference`).
4. The **webhook** `POST /api/v1/webhooks/xendit` does the same when the till is closed. It checks the
   `x-callback-token` header, then asks Xendit for the real status before selling anything.

If the customer pays but the sale can no longer be saved (e.g. the last item was sold meanwhile), the payment is
marked `PAID_NOT_SAVED` with the reason: record it by hand or refund it in the Xendit Dashboard.
Without `XENDIT_SECRET_KEY`, the till offers Cash and E-wallet (the seller checks the customer's phone), as before.

Setup:
1. Xendit Dashboard → Settings → Developers → **API keys**: a secret key with *Money-in* write permission.
   Test keys start with `xnd_development_` (no real money); live keys with `xnd_production_`.
2. Settings → Developers → **Webhooks**: set the Payment Session URL to `https://<your-api>/api/v1/webhooks/xendit`
   and copy the **verification token**.
3. Set `XENDIT_SECRET_KEY` and `XENDIT_WEBHOOK_TOKEN` in `.env` and on Render. Never put the secret key in a frontend.

## Activity history and notifications

Product changes (added, updated, deleted), messages received from other businesses, and connection events
(requested, accepted, declined, withdrawn, ended) are recorded for every business they concern, each from its own
point of view ("You accepted…", "Acme withdrew their request"):
- **History:** `businesses/{id}/activity` in Firestore. The **Activity** page lists it newest first, filtered by kind
  (`GET /businesses/{id}/activity?category=PRODUCTS|MESSAGES|CONNECTIONS&start=<ms>&end=<ms>`; default all).
  Index: `category` + `createdAt` (in `firestore.indexes.json`).
- **Live:** the same entry is pushed to `live/{businessId}/activity` in the Realtime Database. The bell next to the
  business name shows the newest ones (not your own changes) with an unread count. Open pages listen too: the
  Network page and a business's directory page refresh the moment the other side accepts, declines, or withdraws,
  and the Messages list moves a new conversation up right away.
- Recording never fails the change that caused it (a problem is only logged).

### Running everything locally on the emulators
No real Firebase needed. The backend skips the key file when both emulator variables are set:

```powershell
npx firebase-tools emulators:start --only "auth,firestore,database" --project demo-my-business   # terminal 1
$env:FIRESTORE_EMULATOR_HOST="127.0.0.1:8080"; $env:FIREBASE_AUTH_EMULATOR_HOST="127.0.0.1:9099"
$env:FIREBASE_DATABASE_EMULATOR_HOST="127.0.0.1:9000"                                          # live chat
$env:GCLOUD_PROJECT="demo-my-business"; fastapi dev app/main.py                         # terminal 2
```
In both frontends set `VITE_FIREBASE_EMULATORS=true` and `VITE_FIREBASE_PROJECT_ID=demo-my-business`.

## Speed: caching, indexes, and hosting

### Redis cache
Reads go through Redis first (`app/core/cache.py`); only a miss reads Firestore. Measured on real data:
a public profile took about 2,000 ms from Firestore and about 70 ms from the cache.

- **How changes stay visible:** cached keys contain a version number per business. Any change to
  `/api/v1/businesses/{id}/...` bumps that business's version (middleware in `app/main.py`), so the
  next read loads fresh data. Changes that affect another business too (orders, reviews, relationships,
  messages) bump both businesses in their controller.
- **Stock has its own version** (`business:{id}:stock`: inventory, stock history, sales, receipts). A sale,
  a stock change, or anything in the selling app bumps only that, so products, prices, the profile, and the
  rest stay cached through a busy day of selling.
- **The selling app's catalog is one entry** (`pos-catalog:{date}` in the business scope): opening the till
  reads it in one go instead of once per product. Changing a product, variant, price, or the business rebuilds it;
  sales do not. The stock list for a store (`pos-stock:{location}`) is cached in the stock scope.
- **Check it on the live server:** open `/api/health/cache`. It shows whether Redis is connected, how fast
  it answers (`pingMs`), how many keys it holds, and the last Redis error, if any.
- **If you add a new write** that does not go through `/api/v1/businesses/{id}/...` or the `crud` helpers,
  call `cache.bump(...)` for every business it changes.
- **If Redis is down** the API keeps working: it skips Redis for 30 seconds at a time and reads Firestore.
  When Redis comes back, everything cached before the outage is thrown away.
- Set `REDIS_URL` to turn it on (empty = no cache). `CACHE_TTL_SECONDS` (default 86400 = 1 day) is how long data stays cached while nothing changes.
- The frontend also remembers GET responses for 30 seconds and forgets them after any change.

### Indexes and how data is split up
- Lists are **filtered, sorted, and limited by Firestore**, not in Python, using the composite indexes in
  `firestore.indexes.json`. For example: my businesses (`memberUids` + `createdAt`), orders per side
  (`sellerBusinessId` + `orderedAt`), conversations (`businessIds` + `lastMessageAt`), stock history
  (`productId` / `locationId` + `createdAt`, only the newest lines are read), receipts (`date` + `locationId` + `createdAt`, and `locationId` + `createdAt` for all dates).
- `firestore.indexes.json` also turns **off** indexing for big fields that are never searched (descriptions,
  images, message text, order and receipt items). That makes writes faster and cheaper.
- **Deploy the indexes** whenever that file changes (they take a few minutes to build; see Firebase Console →
  Firestore → Indexes): `npx firebase-tools deploy --only firestore:indexes --project <your-project-id>`.
  Until an index is ready, its query falls back to a slower one (`crud.stream_indexed`) and the server log
  says "Firestore index missing", so nothing breaks in the meantime.
- **Adding a query** that filters on one field and sorts on another (or filters on two fields)? Add its index to
  `firestore.indexes.json` and read it with `crud.stream_indexed(query, fallback=simpler_query)`.
- Data is already **partitioned by business**: each business's products, stock, contacts, and so on live
  under `businesses/{id}/...`, so one busy business never slows down another.
- Independent reads run **at the same time** (`app/utils/parallel.py`), e.g. the 11 parts of a public profile.

### Hosting: put everything in one region
Every Firestore or Redis call is a network trip, so the API server should be next to them.

| Service | Where it is |
| ------- | ----------- |
| Firestore | `nam5` (United States). Fixed; it cannot be moved after the database is created. |
| Redis (Redis Cloud) | Singapore |

Pick the Render region closest to both. With Redis in Singapore and Firestore in the US, a US Render region
makes cache misses fast but cache hits slow; a Singapore region makes cache hits fast. The best setup is a
Redis database in the **same region as Render** (Redis Cloud lets you choose it when creating the database).

**Render free plan:** the server goes to sleep after 15 minutes without traffic, and waking it can take
from 30 seconds to several minutes. This is the biggest cause of slow first loads. Use a paid instance,
or ping `/api/health` every 10 minutes (for example with a free uptime monitor like UptimeRobot).

## Image uploads (Cloudflare R2)

Product photos and videos, and business logos/covers, are uploaded to Cloudflare R2
(`POST /api/v1/businesses/{id}/images?kind=product|business`, form field `file`, one file per request).
The API checks what the file really is from its bytes: products take images (JPG, PNG, WEBP, GIF) and
videos (MP4, WEBM, MOV); the logo and cover take images only. Each file can be up to 25 MB.
It stores the file in the `R2_BUCKET` bucket under `product_img/{id}/` or `business_img/{id}/`, and returns its public URL and `mediaType` (`IMAGE` or `VIDEO`).
A product can have any number of photos and videos (`images`, each with a `mediaType`); only an image
can be the primary, which is the thumbnail in lists and in the POS. Media is optional.
The browser shrinks photos before uploading (max 1600 px, WEBP), so uploads and pages stay fast; videos are sent as they are.

Setup (once):
1. Cloudflare dashboard, **R2 > Create bucket** (e.g. `my-business-images`).
2. In the bucket, **Settings > Public access**: turn on the `r2.dev` URL (or connect your own domain). Copy it.
3. **R2 > Manage API tokens > Create token** with *Object Read & Write* for that bucket. Copy the Access Key ID and Secret.
4. Put these in `.env` (and in Render's Environment):
   `R2_ACCOUNT_ID` (shown on the R2 overview page), `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_URL`.

Until these are set, the upload button answers "Image uploads are not set up yet"; everything else works.
After deploying, open `/api/health/r2` in a browser: it checks each R2 setting (without showing the keys) and
tries to open the bucket, and lists anything that is wrong.

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
3. Give the API your Firebase key, in **one** of these ways:
   - **Environment Variable** `FIREBASE_CREDENTIALS_JSON` = the whole contents of the key file (easiest), or
   - **Secret File** named `firebase-service-account.json` (Render puts it at `/etc/secrets/firebase-service-account.json`)
     plus the environment variable `FIREBASE_CREDENTIALS_PATH` = `/etc/secrets/firebase-service-account.json`.
4. **Environment → Environment Variables**:

   | Key | Value |
   | --- | ----- |
   | `CORS_ORIGINS` | your frontend URLs, e.g. `http://localhost:5173,https://my-business.onrender.com` |
   | `ADMIN_EMAILS` | your email |
   | `REDIS_URL` | your Redis connection URL (turns the cache on) |
   | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_URL` | Cloudflare R2, for image uploads |

5. **Health Check Path**: `/api/health`. After deploying, open `/api/health/firebase`: it says `ok`, or exactly what is wrong with the key setup.
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
