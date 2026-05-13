"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Loader2, Mail, Paperclip, X } from "lucide-react";
import { toast } from "sonner";
import { emailsApi } from "@/lib/api/emails";
import type { Property } from "@/lib/api/properties";

/**
 * Wrapper handles open/null. Inner component keys off property.id so state
 * resets cleanly without setState-in-effect.
 */
export function EmailModal({
  property,
  open,
  onClose,
}: {
  property: Property | null;
  open: boolean;
  onClose: () => void;
}) {
  if (!open || !property) return null;
  return <EmailModalInner key={property.id} property={property} onClose={onClose} />;
}

function EmailModalInner({ property, onClose }: { property: Property; onClose: () => void }) {
  const [to, setTo] = useState<string>(property.agency_email ?? "");
  const [subject, setSubject] = useState<string>(
    `Inquiry: ${property.address ?? "Funda listing"}`,
  );
  const [body, setBody] = useState<string>(
    `Hello${property.agency_name ? ` ${property.agency_name}` : ""},\n\n` +
      `I would like to express my interest in the property at ${property.address ?? property.url}.\n\n` +
      `Asking price: ${property.asking_price ?? "—"}\nWOZ: ${property.woz_value ?? "—"}\n\n` +
      `Could you please share more information regarding viewings and the bidding process?\n\n` +
      `Kind regards`,
  );
  const [attachment, setAttachment] = useState<File | null>(null);
  const [sending, setSending] = useState(false);
  const qc = useQueryClient();

  async function onSend(e: React.FormEvent) {
    e.preventDefault();
    if (!to || !subject) return;
    setSending(true);
    try {
      await emailsApi.create({
        to_email: to,
        subject,
        body,
        property_id: property.id,
        property_url: property.url,
        attachment_path: attachment ? attachment.name : undefined,
      });
      toast.success(
        "Email queued. (Google Workspace send wiring lands in a follow-up; record stored in DB + Sheet.)",
      );
      qc.invalidateQueries({ queryKey: ["emails"] });
      qc.invalidateQueries({ queryKey: ["properties"] });
      onClose();
    } catch (err) {
      // @ts-expect-error axios shape
      const msg = err?.response?.data?.detail ?? "Failed to queue email";
      toast.error(typeof msg === "string" ? msg : "Failed to queue email");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4">
      <div className="card flex w-full max-w-2xl flex-col">
        <div className="flex items-center justify-between border-b border-[var(--border)] p-5">
          <div className="flex items-center gap-2">
            <Mail className="h-5 w-5 text-[var(--color-brand-600)]" />
            <h3 className="text-base font-semibold">Send email to agency</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-lg text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={onSend} className="space-y-4 p-5">
          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">
              Property
            </label>
            <div className="rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-3 text-sm">
              <div className="font-medium">{property.address ?? property.url}</div>
              <div className="mt-0.5 truncate text-xs text-[var(--muted-foreground)]">
                {property.url}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">
                To
              </label>
              <input
                type="email"
                className="input"
                value={to}
                onChange={(e) => setTo(e.target.value)}
                required
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">
                Subject
              </label>
              <input
                type="text"
                className="input"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                required
              />
            </div>
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">
              Body
            </label>
            <textarea
              className="input min-h-[180px] resize-y"
              value={body}
              onChange={(e) => setBody(e.target.value)}
              required
            />
          </div>

          <div>
            <label className="mb-1 block text-xs font-medium text-[var(--muted-foreground)]">
              Attachment
            </label>
            <label className="btn-outline cursor-pointer">
              <Paperclip className="h-4 w-4" />
              <span>{attachment ? attachment.name : "Choose file…"}</span>
              <input
                type="file"
                className="hidden"
                onChange={(e) => setAttachment(e.target.files?.[0] ?? null)}
              />
            </label>
          </div>

          <div className="flex justify-end gap-2 border-t border-[var(--border)] pt-4">
            <button type="button" className="btn-ghost" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn-primary" disabled={sending}>
              {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Mail className="h-4 w-4" />}
              Send
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
