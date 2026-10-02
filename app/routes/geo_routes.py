"""Place names for address pickers (delivery zones, addresses). Cached: see app/core/geo.py."""

from fastapi import APIRouter, Depends, Response

from app.core import geo
from app.dependencies.auth import get_current_user

router = APIRouter(prefix="/geo", tags=["Places"], dependencies=[Depends(get_current_user)])

# The browser may keep these for a day too (place names almost never change)
BROWSER_CACHE = "private, max-age=86400"


@router.get("/countries")
def list_countries(response: Response) -> list[dict]:
    """Every country. code: ISO two letters, e.g. PH."""
    response.headers["Cache-Control"] = BROWSER_CACHE
    return geo.countries()


@router.get("/{country}/regions")
def list_regions(country: str, response: Response) -> list[dict]:
    """Philippines: the 17 regions. Elsewhere: states / regions / prefectures."""
    response.headers["Cache-Control"] = BROWSER_CACHE
    return geo.regions(country.upper())


@router.get("/{country}/provinces")
def list_provinces(country: str, region: str, response: Response) -> list[dict]:
    """Philippines only (region = its code). Empty for Metro Manila, which has no provinces."""
    response.headers["Cache-Control"] = BROWSER_CACHE
    return geo.provinces(country.upper(), region)


@router.get("/{country}/cities")
def list_cities(country: str, region: str, response: Response, province: str = "") -> list[dict]:
    """Philippines: cities and municipalities of the province (or of the region, for Metro Manila).
    Elsewhere: cities of the state / region."""
    response.headers["Cache-Control"] = BROWSER_CACHE
    return geo.cities(country.upper(), region, province)


@router.get("/{country}/barangays")
def list_barangays(country: str, city: str, response: Response) -> list[dict]:
    """Philippines only (city = its code)."""
    response.headers["Cache-Control"] = BROWSER_CACHE
    return geo.barangays(country.upper(), city)
