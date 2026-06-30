/**
 * Emails API client. Talks to FastAPI /api/v1/emails.
 * Dual storage: DB (canonical) + Google Sheet (mirror).
 */
import { api, API_BASE } from "../api";

export type EmailRecord = {
  id: number;
  property_id?: number | null;
  property_url?: string | null;
  to_email: string;
  cc_emails?: string | null;
  subject: string;
  body?: string | null;
  body_html?: string | null;
  attachment_path?: string | null;
  status: "queued" | "sent" | "failed" | string;
  error_message?: string | null;
  sent_at?: string | null;
  created_at?: string | null;
};

export type EmailList = {
  items: EmailRecord[];
  total: number;
  limit: number;
  offset: number;
};

export type EmailStats = {
  total: number;
  queued: number;
  sent: number;
  failed: number;
  sent_today: number;
  sent_this_week: number;
};

export type EmailCreate = {
  to_email: string;
  cc_emails?: string;
  subject: string;
  body?: string;
  body_html?: string;
  attachment_path?: string;
  property_id?: number;
  property_url?: string;
};

export type GmailStatus = {
  connected: boolean;
  email_address?: string | null;
  last_updated?: string | null;
  reason?: string | null;
  read_enabled?: boolean; // true once reconnected with gmail.readonly (chat inbox)
};

export const emailsApi = {
  async list(
    params: {
      status?: string;
      property_id?: number;
      from_date?: string;
      to_date?: string;
      limit?: number;
      offset?: number;
    } = {},
  ): Promise<EmailList> {
    const r = await api.get<EmailList>("/emails", { params });
    return r.data;
  },
  async create(payload: EmailCreate): Promise<EmailRecord> {
    const r = await api.post<EmailRecord>("/emails", payload);
    return r.data;
  },
  async stats(): Promise<EmailStats> {
    const r = await api.get<EmailStats>("/emails/stats");
    return r.data;
  },
  async sendNow(id: number): Promise<EmailRecord> {
    const r = await api.post<EmailRecord>(`/emails/${id}/send`);
    return r.data;
  },
  async sendQueued(): Promise<{ attempted: number; sent: number; failed: number }> {
    const r = await api.post<{ attempted: number; sent: number; failed: number }>(
      "/emails/send-queued",
    );
    return r.data;
  },
  async gmailStatus(): Promise<GmailStatus> {
    const r = await api.get<GmailStatus>("/auth/google/status");
    return r.data;
  },
  // Top-level URL — opened in a new tab so Google's redirect lands on
  // the FastAPI callback, not inside the React Router.
  gmailConnectUrl(): string {
    return `${API_BASE}/auth/google/start`;
  },
};
