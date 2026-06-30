/**
 * Conversations (chat inbox) API client. Talks to FastAPI /conversations.
 * A conversation = a Gmail thread; messages = inbound/outbound emails in it.
 */
import { api, API_BASE } from "../api";

export type ConvAttachment = {
  id: number;
  filename: string;
  mime_type?: string | null;
  size?: number | null;
};

export type Conversation = {
  thread_id: string;
  property_id?: number | null;
  property_url?: string | null;
  agency_name?: string | null;
  address?: string | null;
  last_message_preview: string;
  last_message_at?: string | null;
  last_direction: string; // outbound | inbound
  unread_count: number;
  total_messages: number;
};

export type ConversationMessage = {
  id: number;
  direction: string; // outbound | inbound
  from_email?: string | null;
  to_email: string;
  subject: string;
  body?: string | null;
  body_html?: string | null;
  is_read: boolean;
  attachments: ConvAttachment[];
  sent_at?: string | null;
  created_at?: string | null;
};

export const conversationsApi = {
  async list(params: { q?: string; limit?: number; offset?: number } = {}): Promise<{
    items: Conversation[];
    total: number;
  }> {
    const r = await api.get("/conversations", { params });
    return r.data;
  },
  async messages(threadId: string): Promise<{ items: ConversationMessage[] }> {
    const r = await api.get(`/conversations/${encodeURIComponent(threadId)}/messages`);
    return r.data;
  },
  async reply(
    threadId: string,
    payload: { body: string; body_html?: string; files?: File[] },
  ): Promise<ConversationMessage> {
    const fd = new FormData();
    fd.append("body", payload.body);
    if (payload.body_html) fd.append("body_html", payload.body_html);
    for (const f of payload.files ?? []) fd.append("files", f);
    const r = await api.post(`/conversations/${encodeURIComponent(threadId)}/reply`, fd);
    return r.data;
  },
  async markRead(threadId: string): Promise<{ updated: number }> {
    const r = await api.post(`/conversations/${encodeURIComponent(threadId)}/read`);
    return r.data;
  },
  async unreadCount(): Promise<{ unread: number }> {
    const r = await api.get("/conversations/unread-count");
    return r.data;
  },
  attachmentUrl(id: number): string {
    return `${API_BASE}/conversations/attachments/${id}`;
  },
};
