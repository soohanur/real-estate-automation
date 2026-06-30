"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Mail, MessageSquare } from "lucide-react";
import { emailsApi } from "@/lib/api/emails";
import { ConversationList } from "@/components/chat/conversation-list";
import { ChatThread } from "@/components/chat/chat-thread";
import { cn } from "@/lib/utils";

export default function EmailsPage() {
  const [threadId, setThreadId] = useState<string | null>(null);

  // Deep-link / restore selected thread via ?thread= (also drives mobile back).
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("thread");
    if (t) setThreadId(t);
  }, []);

  const select = (t: string | null) => {
    setThreadId(t);
    const url = new URL(window.location.href);
    if (t) url.searchParams.set("thread", t);
    else url.searchParams.delete("thread");
    window.history.replaceState({}, "", url);
  };

  const { data: gmail } = useQuery({
    queryKey: ["gmail", "status"],
    queryFn: emailsApi.gmailStatus,
    refetchInterval: 60_000,
  });

  const connected = gmail?.connected === true;
  const readEnabled = gmail?.read_enabled === true;

  return (
    <div className="flex h-full min-h-0 flex-col pb-[calc(3.5rem+env(safe-area-inset-bottom))] md:pb-0">
      {connected === false || (connected && !readEnabled) ? (
        <GmailBanner connected={connected} readEnabled={readEnabled} />
      ) : null}

      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden md:grid-cols-[360px_1fr]">
        {/* Conversation list — hidden on mobile when a thread is open */}
        <div
          className={cn(
            "min-h-0 border-r border-[var(--border)] bg-[var(--surface)]",
            threadId ? "hidden md:block" : "block",
          )}
        >
          <ConversationList selectedThreadId={threadId} onSelect={select} />
        </div>

        {/* Thread — hidden on mobile when no thread selected */}
        <div className={cn("min-h-0 bg-[var(--surface-2)]", threadId ? "block" : "hidden md:block")}>
          {threadId ? (
            <ChatThread threadId={threadId} gmailReady={connected} onBack={() => select(null)} />
          ) : (
            <div className="grid h-full place-items-center p-8 text-center">
              <div className="text-[var(--muted-foreground)]">
                <MessageSquare className="mx-auto mb-3 h-10 w-10 opacity-40" />
                <p className="text-sm">Select a conversation to read and reply.</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function GmailBanner({ connected, readEnabled }: { connected: boolean; readEnabled: boolean }) {
  const url = emailsApi.gmailConnectUrl();
  const msg = !connected
    ? "Connect Gmail to send and receive emails."
    : "Reconnect Gmail to receive replies — read access not yet granted.";
  return (
    <div className="flex shrink-0 flex-wrap items-center gap-3 border-b border-amber-200 bg-amber-50 px-4 py-2.5 text-sm text-amber-900">
      <Mail className="h-4 w-4 shrink-0" />
      <span className="min-w-0 flex-1">{msg}</span>
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-2 rounded-md bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-700"
      >
        {connected ? "Reconnect Gmail" : "Connect Gmail"}
      </a>
    </div>
  );
}
