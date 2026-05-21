import { api } from "../api";
import type { Property } from "./properties";

// LatestProperty mirrors PropertyOut on the backend (full sheet schema).
// Still present so the Property type isn't broken — the dashboard panel
// itself no longer renders the table.
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

export type EmailReportBucket = {
  bucket: string;
  sent: number;
  queued: number;
  failed: number;
  total: number;
};

export type EmailReportGranularity = "day" | "month" | "year";

export type EmailReport = {
  granularity: EmailReportGranularity;
  from_date: string;
  to_date: string;
  buckets: EmailReportBucket[];
  totals: EmailReportBucket;
};

export type EmailReportPeriod = "day" | "week" | "month" | "year" | "all" | "custom";

export const dashboardApi = {
  async stats(): Promise<DashboardStats> {
    const r = await api.get<DashboardStats>("/dashboard/stats");
    return r.data;
  },
  async emailReport(params: {
    period: EmailReportPeriod;
    from_date?: string;
    to_date?: string;
    group_by?: EmailReportGranularity;
  }): Promise<EmailReport> {
    const r = await api.get<EmailReport>("/dashboard/email-report", { params });
    return r.data;
  },
};
