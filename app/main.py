from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
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


# Not versioned: hosting platforms (e.g. Render) check this path to see if the app is up
@app.get("/api/health", tags=["Health"])
def health_check():
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
    admin_routes,
):
    app.include_router(router_module.router, prefix=API_V1_PREFIX)
