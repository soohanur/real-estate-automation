import { api } from "../api";
import type { Property } from "./properties";

// LatestProperty mirrors PropertyOut on the backend (full sheet schema)
// so the dashboard's Latest Scrapes table matches Global Data exactly.
export type LatestProperty = Property;

export type DashboardStats = {
  total_scraped: number;
  scraped_today: number;
  total_emails: number;
  emails_sent: number;
  emails_sent_today: number;
  emails_queued: number;
  emails_failed: number;
  not_emailed: number;
  latest_scrapes: LatestProperty[];
};

export const dashboardApi = {
  async stats(): Promise<DashboardStats> {
    const r = await api.get<DashboardStats>("/dashboard/stats");
    return r.data;
  },
};
