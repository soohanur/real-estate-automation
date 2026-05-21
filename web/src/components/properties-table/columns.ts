/**
 * Column definitions for PropertiesTable. The order here is the visual
 * order on screen and mirrors the Google Sheet HEADERS, with
 * Listed Since + DOM moved before Asking Price (as per spec) and
 * Images placed right after Bidding (edit) so the photo strip sits in
 * the financial section.
 */
import type { ColumnDef } from "./types";

export const COLUMNS: ColumnDef[] = [
  { key: "scrape_date", label: "Scrape Date", sortable: true, width: "130px" },
  { key: "address", label: "Address", sortable: true, width: "240px" },
  { key: "listed_since", label: "Listed Since", sortable: true, width: "110px" },
  { key: "days_on_market", label: "DOM", sortable: true, width: "70px" },
  { key: "asking_price", label: "Asking", sortable: true, width: "110px" },
  { key: "woz_value", label: "WOZ", sortable: true, width: "110px" },
  { key: "suggested_bid", label: "AI Suggested", sortable: true, width: "130px" },
  { key: "bidding_price", label: "Bidding Price", width: "150px" },
  { key: "images", label: "Images", width: "140px" },
  { key: "price_per_m2", label: "€/m²", width: "110px" },
  { key: "living_area", label: "m²", width: "70px" },
  { key: "plot_area", label: "Plot m²", width: "80px" },
  { key: "rooms", label: "Rooms", width: "70px" },
  { key: "bedrooms", label: "Beds", width: "60px" },
  { key: "construction_year", label: "Year", width: "70px" },
  { key: "property_type", label: "Type", sortable: true, width: "180px" },
  { key: "energy_label", label: "Energy", sortable: true, width: "70px" },
  { key: "heating", label: "Heating", width: "140px" },
  { key: "insulation", label: "Insulation", width: "150px" },
  { key: "maintenance_inside", label: "Maint. In", width: "120px" },
  { key: "maintenance_outside", label: "Maint. Out", width: "120px" },
  { key: "garden", label: "Garden", width: "140px" },
  { key: "garden_orientation", label: "Orient.", width: "120px" },
  { key: "parking", label: "Parking", width: "140px" },
  { key: "vve", label: "VVE", width: "100px" },
  { key: "erfpacht", label: "Erfpacht", width: "120px" },
  { key: "acceptance", label: "Acceptance", width: "140px" },
  { key: "description", label: "Description", width: "260px" },
  { key: "agency_name", label: "Agency", sortable: true, width: "160px" },
  { key: "agency_phone", label: "Phone", width: "130px" },
  { key: "agency_email", label: "Email", width: "180px" },
  { key: "agency_website", label: "Website", width: "180px" },
  { key: "sheet_tab", label: "Range", width: "120px" },
  { key: "email_status", label: "Status", sortable: true, width: "110px" },
];

export const ROW_HEIGHT = 48;
export const ACTIONS_WIDTH = "108px";

/** Pre-computed grid-template-columns string so header + every row
 * stay aligned without per-render string concatenation. */
export const GRID_TEMPLATE = COLUMNS.map((c) => c.width).join(" ") + ` ${ACTIONS_WIDTH}`;

/** Sum of column widths in pixels. Used as min-width on the grid so
 * horizontal overflow scrolls inside the parent container. */
export const TOTAL_GRID_WIDTH = [...COLUMNS.map((c) => c.width), ACTIONS_WIDTH]
  .map((w) => parseInt(w.replace("px", ""), 10) || 0)
  .reduce((a, b) => a + b, 0);
