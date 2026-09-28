import re

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core import cache
from app.core.config import settings
from app.core.firebase import get_firebase_app
from app.routes import (
    admin_routes,
    business_routes,
    catalog_routes,
    commerce_routes,
    directory_routes,
    inventory_routes,
    network_routes,
    order_routes,
    profile_routes,
    pos_routes,
    upload_routes,
)

# Every route is versioned: /api/v1/... When a breaking change is needed, add /api/v2
# routers next to these, so apps that use v1 keep working until they update.
API_V1_PREFIX = "/api/v1"

app = FastAPI(title=settings.app_name, version="1.0.0")

# Lets the React app (running on another port) call this API from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Cache clearing ----------------------------------------------------------------------
# After any successful change to /api/v1/businesses/{id}/..., everything cached for that
# business (and the directory) is marked outdated. See app/core/cache.py for how this works.
BUSINESS_URL = re.compile(r"^/api/v1/businesses/([^/]+)")
READ_ONLY_POSTS = ("/orders/quote",)  # POSTs that don't change anything
# Writes that only change stock (stock records, walk-in sales, the selling app)
STOCK_ONLY_URL = re.compile(r"^/api/v1/businesses/[^/]+/(inventory|sales|pos)(/|$)")


@app.middleware("http")
async def clear_cache_after_changes(request: Request, call_next):
    response = await call_next(request)
    is_change = request.method in ("POST", "PUT", "PATCH", "DELETE") and response.status_code < 400
    if is_change and not request.url.path.endswith(READ_ONLY_POSTS):
        match = BUSINESS_URL.match(request.url.path)
        if match and STOCK_ONLY_URL.match(request.url.path):
            # A sale or stock change: only the stock side is outdated (products, profile... stay cached)
            cache.bump(cache.stock_scope(match.group(1)))
        elif match:
            cache.bump(cache.business_scope(match.group(1)), cache.DIRECTORY)
    return response


# Not versioned: hosting platforms (e.g. Render) check this path to see if the app is up
@app.get("/api/health", tags=["Health"])
def health_check():
    return {"status": "ok"}


@app.get("/api/health/cache", tags=["Health"])
def cache_check():
    """Open this in a browser after deploying: is Redis connected, how fast, and how many keys it holds."""
    return cache.status()


@app.get("/api/health/firebase", tags=["Health"])
def firebase_check():
    """Open this in a browser after deploying: it says whether the Firebase key could be loaded."""
    try:
        get_firebase_app()
    except Exception as error:  # report any setup problem instead of a bare 500
        return JSONResponse(status_code=503, content={"status": "error", "detail": str(error)})
    return {"status": "ok"}


# Version 1 of the API, e.g. /api/v1/businesses
for router_module in (
    directory_routes,
    business_routes,
    profile_routes,
    catalog_routes,
    inventory_routes,
    commerce_routes,
    order_routes,
    network_routes,
    pos_routes,
    upload_routes,
    admin_routes,
):
    app.include_router(router_module.router, prefix=API_V1_PREFIX)
