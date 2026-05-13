/**
 * Properties API client. Talks to FastAPI /api/v1/properties.
 * Data source: DB (which mirrors the Google Sheet via /sync).
 */
import { api } from "../api";

export type Property = {
  id: number;
  url: string;
  scrape_date?: string | null;
  address?: string | null;
  listed_since?: string | null;
  days_on_market?: string | null;
  asking_price?: string | null;
  woz_value?: string | null;
  suggested_bid?: string | null;
  bidding_price?: string | null;
  price_per_m2?: string | null;
  living_area?: string | null;
  plot_area?: string | null;
  rooms?: string | null;
  bedrooms?: string | null;
  construction_year?: string | null;
  property_type?: string | null;
  energy_label?: string | null;
  heating?: string | null;
  insulation?: string | null;
  maintenance_inside?: string | null;
  maintenance_outside?: string | null;
  garden?: string | null;
  garden_orientation?: string | null;
  parking?: string | null;
  vve?: string | null;
  erfpacht?: string | null;
  acceptance?: string | null;
  description?: string | null;
  images?: string | null;
  agency_name?: string | null;
  agency_phone?: string | null;
  agency_email?: string | null;
  agency_website?: string | null;
  email_status?: string | null;
  notes?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  last_synced_at?: string | null;
};

export type PropertyList = {
  items: Property[];
  total: number;
  limit: number;
  offset: number;
};

export type ListParams = {
  q?: string;
  email_status?: string;
  property_type?: string;
  energy_label?: string;
  agency_name?: string;
  days_back?: number;
  sort?: string;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
};

export type FilterOptions = {
  property_type: string[];
  energy_label: string[];
  agency_name: string[];
  email_status: string[];
};

export const propertiesApi = {
  async list(params: ListParams = {}): Promise<PropertyList> {
    const r = await api.get<PropertyList>("/properties", { params });
    return r.data;
  },
  async get(id: number): Promise<Property> {
    const r = await api.get<Property>(`/properties/${id}`);
    return r.data;
  },
  async update(id: number, patch: { notes?: string; email_status?: string; bidding_price?: string }): Promise<Property> {
    const r = await api.patch<Property>(`/properties/${id}`, patch);
    return r.data;
  },
  async sync(): Promise<{ inserted: number; updated: number; total_rows: number }> {
    const r = await api.post("/properties/sync");
    return r.data;
  },
  async filters(): Promise<FilterOptions> {
    const r = await api.get<FilterOptions>("/properties/filters");
    return r.data;
  },
};
