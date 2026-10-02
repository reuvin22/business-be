"""Place names for address pickers: countries, then their regions, provinces, cities, and barangays.

- Philippines: the official PSGC lists (https://psgc.gitlab.io/api): region > province > city/municipality
  > barangay. Metro Manila (NCR) has no provinces: its cities hang straight under the region.
- Other countries: CountriesNow (https://countriesnow.space): state/region > city.

Every list is cached in Redis for 30 days and shared by everyone (place names almost never change),
so only the very first person to open a list waits for the outside service.
"""

import httpx
from fastapi import HTTPException, status

from app.core import cache

PSGC = "https://psgc.gitlab.io/api"
COUNTRIES_NOW = "https://countriesnow.space/api/v0.1"
PHILIPPINES = "PH"
CACHE_SECONDS = 30 * 24 * 60 * 60

Place = dict[str, str]  # {"code": ..., "name": ...}


def _fetch(url: str) -> object:
    try:
        response = httpx.get(url, timeout=20, follow_redirects=True)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not load the list of places right now. You can type the name instead.",
        ) from error


def _cached(key: str, load) -> list[Place]:
    return cache.remember(cache.GEO, key, load, to_json=lambda places: places, from_json=lambda data: data, ttl_seconds=CACHE_SECONDS)


def _sorted(places: list[Place]) -> list[Place]:
    return sorted(places, key=lambda place: place["name"].lower())


def _psgc(path: str) -> list[dict]:
    data = _fetch(f"{PSGC}/{path}")
    return data if isinstance(data, list) else []


def _countries_now(path: str) -> dict:
    data = _fetch(f"{COUNTRIES_NOW}/{path}")
    if not isinstance(data, dict) or data.get("error"):
        return {}
    return data


# ---- The levels ---------------------------------------------------------------------------------


def countries() -> list[Place]:
    """Every country: code = ISO 3166 two letters (e.g. PH)."""

    def load():
        found = _countries_now("countries/iso").get("data") or []
        return _sorted([{"code": c["Iso2"], "name": c["name"]} for c in found if c.get("Iso2") and c.get("name")])

    return _cached("countries", load)


def regions(country: str) -> list[Place]:
    """Philippines: the 17 regions, e.g. "Region IV-A (CALABARZON)". Elsewhere: states / regions / prefectures."""
    if country == PHILIPPINES:

        def load():
            return _sorted([{"code": r["code"], "name": _region_name(r)} for r in _psgc("regions.json")])

        return _cached("ph:regions", load)

    def load_states():
        found = (_countries_now(f"countries/states/q?iso2={country}").get("data") or {}).get("states") or []
        return _sorted([{"code": s["name"], "name": s["name"]} for s in found if s.get("name")])

    return _cached(f"{country}:regions", load_states)


def provinces(country: str, region: str) -> list[Place]:
    """Philippines only. Empty for Metro Manila (NCR), which has no provinces."""
    if country != PHILIPPINES:
        return []
    return _cached(
        f"ph:provinces:{region}",
        lambda: _sorted([{"code": p["code"], "name": p["name"]} for p in _psgc(f"regions/{region}/provinces.json")]),
    )


def cities(country: str, region: str, province: str = "") -> list[Place]:
    """Philippines: the cities and municipalities of a province (or, for NCR, of the region).
    Elsewhere: the cities of a state / region (region = its name)."""
    if country == PHILIPPINES:
        path = f"provinces/{province}/cities-municipalities.json" if province else f"regions/{region}/cities-municipalities.json"
        return _cached(
            f"ph:cities:{province or region}",
            lambda: _sorted([{"code": c["code"], "name": c["name"]} for c in _psgc(path)]),
        )

    def load():
        query = httpx.QueryParams({"country": _country_name(country), "state": region})
        found = _countries_now(f"countries/state/cities/q?{query}").get("data") or []
        return _sorted([{"code": name, "name": name} for name in dict.fromkeys(found) if name])

    return _cached(f"{country}:cities:{region}", load)


def barangays(country: str, city: str) -> list[Place]:
    """Philippines only: the barangays of a city or municipality."""
    if country != PHILIPPINES:
        return []
    return _cached(
        f"ph:barangays:{city}",
        lambda: _sorted([{"code": b["code"], "name": b["name"]} for b in _psgc(f"cities-municipalities/{city}/barangays.json")]),
    )


def _region_name(region: dict) -> str:
    """ "Region IV-A (CALABARZON)", "National Capital Region (NCR)", or just the name when both are the same."""
    official, common = region.get("regionName", ""), region.get("name", "")
    return f"{official} ({common})" if official and common and official != common else official or common


def _country_name(code: str) -> str:
    return next((c["name"] for c in countries() if c["code"] == code), code)
