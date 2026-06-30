"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { Search } from "lucide-react";
import { conversationsApi, type Conversation } from "@/lib/api/conversations";
import { cn } from "@/lib/utils";

function title(c: Conversation) {
  return c.agency_name || c.address || c.last_message_preview || "Conversation";
}
function initial(c: Conversation) {
  return (title(c).trim()[0] || "?").toUpperCase();
}

export function ConversationList({
  selectedThreadId,
  onSelect,
}: {
  selectedThreadId: string | null;
  onSelect: (threadId: string) => void;
}) {
  const [q, setQ] = useState("");

  const { data, isLoading } = useQuery({
    queryKey: ["conversations", "list", q],
    queryFn: () => conversationsApi.list({ q: q || undefined, limit: 200 }),
    refetchInterval: 15_000,
  });

  const items = data?.items ?? [];

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-[var(--border)] p-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--muted-foreground)]" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search conversations…"
            className="input h-9 w-full pl-9 text-sm"
          />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="p-8 text-center text-sm text-[var(--muted-foreground)]">Loading…</div>
        ) : items.length === 0 ? (
          <div className="p-8 text-center text-sm text-[var(--muted-foreground)]">
            No conversations yet. Send an email from a property to start one.
          </div>
        ) : (
          items.map((c) => {
            const active = c.thread_id === selectedThreadId;
            return (
              <button
                key={c.thread_id}
                type="button"
                onClick={() => onSelect(c.thread_id)}
                className={cn(
                  "flex w-full items-center gap-3 border-b border-[var(--border)] px-3 py-3 text-left hover:bg-[var(--muted)]",
                  active && "bg-[var(--color-brand-50)]",
                )}
              >
                <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-[var(--surface-2)] text-sm font-semibold text-[var(--color-brand-700)]">
                  {initial(c)}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-medium">{title(c)}</span>
                    {c.last_message_at && (
                      <span className="shrink-0 text-[10px] text-[var(--muted-foreground)]">
                        {formatDistanceToNow(new Date(c.last_message_at), { addSuffix: false })}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate text-xs text-[var(--muted-foreground)]">
                      {c.last_direction === "outbound" ? "You: " : ""}
                      {c.last_message_preview || "—"}
                    </span>
                    {c.unread_count > 0 && (
                      <span className="grid h-5 min-w-5 shrink-0 place-items-center rounded-full bg-[var(--color-brand-600)] px-1.5 text-[10px] font-bold text-white">
                        {c.unread_count}
                      </span>
                    )}
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </div>
  );
}
