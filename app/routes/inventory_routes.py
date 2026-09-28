"""Stock levels per location, and walk-in sales."""

from fastapi import APIRouter, Depends, Query, status
from google.cloud.firestore import Client

from app.controllers import inventory_controller, sale_controller
from app.core.firebase import get_db
from app.dependencies.business_access import BusinessAccess, get_business_access
from app.models.inventory import InventoryItem, StockMovement
from app.models.trade import Sale
from app.schemas.inventory import InventoryAdjustIn, InventoryIn, InventoryUpdateIn
from app.schemas.sale import SaleIn

router = APIRouter(prefix="/businesses/{business_id}", tags=["Inventory & sales"])

# ---- Inventory ----------------------------------------------------------------------------


@router.get("/inventory", response_model=list[InventoryItem])
def list_inventory(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return inventory_controller.list_inventory(db, access.business_id)


@router.post("/inventory", response_model=InventoryItem, status_code=status.HTTP_201_CREATED)
def create_inventory(
    inventory_in: InventoryIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)
):
    return inventory_controller.create_inventory(db, access, inventory_in)


@router.put("/inventory/{inventory_id}", response_model=InventoryItem)
def update_inventory(
    inventory_id: str,
    update_in: InventoryUpdateIn,
    db: Client = Depends(get_db),
    access: BusinessAccess = Depends(get_business_access),
):
    return inventory_controller.update_inventory(db, access, inventory_id, update_in)


@router.post("/inventory/{inventory_id}/adjust", response_model=InventoryItem)
def adjust_inventory(
    inventory_id: str,
    adjust_in: InventoryAdjustIn,
    db: Client = Depends(get_db),
    access: BusinessAccess = Depends(get_business_access),
):
    return inventory_controller.adjust_inventory(db, access, inventory_id, adjust_in)


@router.delete("/inventory/{inventory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_inventory(inventory_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    inventory_controller.delete_inventory(db, access, inventory_id)


# ---- Stock history ------------------------------------------------------------------------


@router.get("/stock-movements", response_model=list[StockMovement])
def list_stock_movements(
    product_id: str | None = None,
    location_id: str | None = None,
    limit: int = Query(default=300, ge=1, le=1000),
    db: Client = Depends(get_db),
    access: BusinessAccess = Depends(get_business_access),
):
    """Every change to quantities on hand, newest first. Filter with ?product_id= and/or ?location_id=."""
    return inventory_controller.list_movements(db, access.business_id, product_id, location_id, limit)


# ---- Walk-in sales ------------------------------------------------------------------------


@router.get("/sales", response_model=list[Sale])
def list_sales(db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return sale_controller.list_sales(db, access.business_id)


@router.post("/sales", response_model=Sale, status_code=status.HTTP_201_CREATED)
def record_sale(sale_in: SaleIn, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    return sale_controller.record_sale(db, access, sale_in)


@router.delete("/sales/{sale_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sale(sale_id: str, db: Client = Depends(get_db), access: BusinessAccess = Depends(get_business_access)):
    sale_controller.delete_sale(db, access, sale_id)
