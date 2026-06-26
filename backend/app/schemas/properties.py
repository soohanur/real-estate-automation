"""Shared property response schema.

PropertyOut is used by BOTH the properties router and the dashboard router
(latest_scrapes), so it lives here instead of inside one router — that keeps
routers from importing each other.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PropertyOut(BaseModel):
    id: int
    url: str
    scrape_date: Optional[str] = None
    address: Optional[str] = None
    listed_since: Optional[str] = None
    days_on_market: Optional[str] = None
    asking_price: Optional[str] = None
    woz_value: Optional[str] = None
    suggested_bid: Optional[str] = None
    bidding_price: Optional[str] = None
    price_per_m2: Optional[str] = None
    living_area: Optional[str] = None
    plot_area: Optional[str] = None
    rooms: Optional[str] = None
    bedrooms: Optional[str] = None
    construction_year: Optional[str] = None
    property_type: Optional[str] = None
    energy_label: Optional[str] = None
    heating: Optional[str] = None
    insulation: Optional[str] = None
    maintenance_inside: Optional[str] = None
    maintenance_outside: Optional[str] = None
    garden: Optional[str] = None
    garden_orientation: Optional[str] = None
    parking: Optional[str] = None
    vve: Optional[str] = None
    erfpacht: Optional[str] = None
    acceptance: Optional[str] = None
    description: Optional[str] = None
    images: Optional[str] = None
    agency_name: Optional[str] = None
    agency_phone: Optional[str] = None
    agency_email: Optional[str] = None
    agency_website: Optional[str] = None
    sheet_tab: Optional[str] = None
    email_status: Optional[str] = "not_sent"
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None

    class Config:
        from_attributes = True
