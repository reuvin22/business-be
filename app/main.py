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

app = FastAPI(title=settings.app_name)

# Lets the React app (running on another port) call this API from the browser
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["Health"])
def health_check():
    return {"status": "ok"}


# Every route lives under /api, e.g. /api/businesses
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
    app.include_router(router_module.router, prefix="/api")
