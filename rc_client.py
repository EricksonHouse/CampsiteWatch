"""
ReserveCalifornia API client.

Endpoint schema verified against a working, currently-maintained open-source
tool (github.com/ggydush/campsites) as of Aug 2026. ReserveCalifornia runs on
Tyler Technologies' recreation-management platform. Endpoints:

  GET  {BASE}/rdr/fd/citypark/namecontains/{query}   -> search parks by name
  POST {BASE}/rdr/search/place                       -> list facilities in a park
  POST {BASE}/rdr/search/grid                        -> unit-level availability grid

This is unofficial, undocumented, and can change without notice. If requests
start failing, the first thing to check is whether the domain or paths below
have moved (open reservecalifornia.com in a browser, do a search, and inspect
the Network tab for the current request to `.../search/grid`).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import requests

logger = logging.getLogger("campwatch.rc_client")

BASE_URL = "https://california-rdr.prod.cali.rd12.recreation-management.tylerapp.com"
SEARCH_ENDPOINT = "/rdr/fd/citypark/namecontains/"
PLACE_ENDPOINT = "/rdr/search/place"
GRID_ENDPOINT = "/rdr/search/grid"
BOOKING_URL = "https://www.reservecalifornia.com/"

DEFAULT_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}


class ReserveCaliforniaError(RuntimeError):
    pass


def _get(url: str, params: dict[str, Any] | None = None) -> Any:
    resp = requests.get(url, params=params, headers=DEFAULT_HEADERS, timeout=15)
    if resp.status_code != 200:
        raise ReserveCaliforniaError(f"GET {url} -> {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def _post(url: str, data: dict[str, Any]) -> Any:
    resp = requests.post(
        url, data=json.dumps(data), headers=DEFAULT_HEADERS, timeout=15
    )
    if resp.status_code != 200:
        raise ReserveCaliforniaError(f"POST {url} -> {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def find_park(query: str) -> list[dict[str, str]]:
    """Search parks by name. Returns [{'name', 'place_id'}, ...]."""
    url = f"{BASE_URL}{SEARCH_ENDPOINT}{requests.utils.quote(query)}"
    results = _get(url)
    if not results:
        raise ReserveCaliforniaError(f"No park found matching '{query}'")
    return [{"name": r["Name"], "place_id": r["PlaceId"]} for r in results]


def find_facilities(place_id: str) -> list[dict[str, str]]:
    """Given a park's place_id, list its bookable facilities/campgrounds
    with their facility_id (this is the ID campwatch.py needs)."""
    url = f"{BASE_URL}{PLACE_ENDPOINT}"
    data = {"PlaceId": place_id, "StartDate": datetime.today().strftime("%m-%d-%Y")}
    response = _post(url, data)
    selected = response.get("SelectedPlace")
    if not selected:
        raise ReserveCaliforniaError(f"No facilities found for place_id {place_id}")
    out = []
    for facility in selected["Facilities"].values():
        out.append({"name": facility["Name"], "facility_id": str(facility["FacilityId"])})
    return sorted(out, key=lambda x: x["name"])


@dataclass
class Unit:
    unit_id: int
    name: str
    short_name: str
    is_ada: bool
    allow_web_booking: bool
    available_dates: list[str]  # ISO date strings with at least one free slice

    def matches_keywords(self, keywords: list[str]) -> bool:
        if not keywords:
            return True
        haystack = f"{self.name} {self.short_name}".lower()
        return any(k.lower() in haystack for k in keywords)


def get_availability(
    facility_id: str, start_date: datetime, end_date: datetime
) -> tuple[str, list[Unit]]:
    """Fetch the availability grid for a facility over a date range.

    Returns (facility_name, list of Units that have >=1 free date in range).
    Units with zero availability are excluded to keep downstream filtering cheap.
    """
    url = f"{BASE_URL}{GRID_ENDPOINT}"
    data = {
        "FacilityId": facility_id,
        "StartDate": start_date.strftime("%Y-%m-%d"),
        "EndDate": end_date.strftime("%Y-%m-%d"),
    }
    response = _post(url, data)
    facility = response.get("Facility")
    if not facility:
        raise ReserveCaliforniaError(f"Facility {facility_id} not found or returned no data")

    facility_name = facility.get("Name", f"Facility {facility_id}")
    units_raw = facility.get("Units", {})

    units: list[Unit] = []
    for unit_id, unit in units_raw.items():
        free_dates = [
            slice_["Date"]
            for slice_ in unit.get("Slices", {}).values()
            if slice_.get("IsFree")
        ]
        if not free_dates:
            continue
        units.append(
            Unit(
                unit_id=int(unit_id),
                name=unit.get("Name", ""),
                short_name=unit.get("ShortName", ""),
                is_ada=bool(unit.get("IsAda", False)),
                allow_web_booking=bool(unit.get("AllowWebBooking", True)),
                available_dates=sorted(free_dates),
            )
        )
    return facility_name, units


def booking_link(facility_id: str) -> str:
    # ReserveCalifornia's SPA routes by facility internally; the safe, stable
    # link is the homepage search -- deep links have changed before.
    return f"{BOOKING_URL}?facility={facility_id}"


def polite_get_availability(
    facility_id: str, start_date: datetime, end_date: datetime, min_gap_seconds: float = 1.0
) -> tuple[str, list[Unit]]:
    """Wrapper that enforces a minimum delay before the request, so a config
    mistake (e.g. many facilities on a short interval) can't hammer the site."""
    time.sleep(min_gap_seconds)
    return get_availability(facility_id, start_date, end_date)
