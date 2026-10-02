"""Place names for the pickers. The outside services are faked: tests never call them."""

import httpx
import pytest
from fastapi import HTTPException

from app.controllers.pricing import find_delivery_zone
from app.core import geo
from app.core.config import settings
from app.models.profile import DeliveryZone
from app.schemas.order import Address

PSGC_ANSWERS = {
    f"{geo.PSGC}/regions.json": [
        {"code": "040000000", "name": "CALABARZON", "regionName": "Region IV-A"},
        {"code": "130000000", "name": "NCR", "regionName": "National Capital Region"},
    ],
    f"{geo.PSGC}/regions/130000000/provinces.json": [],
    f"{geo.PSGC}/regions/130000000/cities-municipalities.json": [{"code": "133900000", "name": "City of Manila"}],
}


@pytest.fixture
def calls(monkeypatch):
    """Answers like the real services, and counts every call that reaches them. The cache is on."""
    monkeypatch.setattr(settings, "redis_url", "redis://test")  # the fake Redis from conftest is used
    made = []

    def fake_get(url, **kwargs):
        made.append(url)
        if url not in PSGC_ANSWERS:
            return httpx.Response(503, request=httpx.Request("GET", url))
        return httpx.Response(200, json=PSGC_ANSWERS[url], request=httpx.Request("GET", url))

    monkeypatch.setattr(geo.httpx, "get", fake_get)
    return made


def test_regions_show_both_names(calls):
    assert geo.regions("PH") == [
        {"code": "130000000", "name": "National Capital Region (NCR)"},
        {"code": "040000000", "name": "Region IV-A (CALABARZON)"},
    ]


def test_metro_manila_has_cities_but_no_provinces(calls):
    assert geo.provinces("PH", "130000000") == []
    assert geo.cities("PH", "130000000") == [{"code": "133900000", "name": "City of Manila"}]


def test_lists_come_from_the_cache_after_the_first_time(calls):
    geo.regions("PH")
    geo.regions("PH")
    geo.regions("PH")
    assert calls == [f"{geo.PSGC}/regions.json"]


def test_a_service_that_is_down_says_so(calls):
    with pytest.raises(HTTPException) as error:
        geo.barangays("PH", "999")
    assert error.value.status_code == 502
    assert "type the name" in error.value.detail


def test_zones_match_by_country_too():
    ph_zone = DeliveryZone(id="z1", country="Philippines", delivery_fee=100)
    manila = DeliveryZone(id="z2", country="Philippines", region="National Capital Region (NCR)", delivery_fee=50)
    old_zone = DeliveryZone(id="z3", region="Region IV-A (CALABARZON)", delivery_fee=80)  # made before countries

    zones = [ph_zone, manila, old_zone]
    assert find_delivery_zone(zones, Address(region="National Capital Region (NCR)")).id == "z2"
    assert find_delivery_zone(zones, Address(region="Region VII")).id == "z1"
    assert find_delivery_zone(zones, Address(region="Region IV-A (CALABARZON)")).id == "z3"
    assert find_delivery_zone(zones, Address(country="Japan", region="Tokyo")) is None
