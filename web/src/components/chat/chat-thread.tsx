"use client";

import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileText, Loader2 } from "lucide-react";
import { toast } from "sonner";
import {
  conversationsApi,
  type ConversationMessage,
} from "@/lib/api/conversations";
import { cn, formatDate } from "@/lib/utils";
import { ReplyComposer } from "./reply-composer";

type ThreadData = { items: ConversationMessage[] };

export function ChatThread({
  threadId,
  gmailReady,
  onBack,
}: {
  threadId: string;
  gmailReady: boolean;
  onBack?: () => void;
}) {
  const qc = useQueryClient();
  const bottomRef = useRef<HTMLDivElement>(null);
  const msgKey = ["conversations", "messages", threadId];

  const { data, isLoading } = useQuery<ThreadData>({
    queryKey: msgKey,
    queryFn: () => conversationsApi.messages(threadId),
    refetchInterval: 8_000,
    placeholderData: (prev) => prev,
  });

  const messages = data?.items ?? [];

  // Mark read on open / when new inbound arrives, then refresh the list badge.
  useEffect(() => {
    if (!threadId) return;
    conversationsApi
      .markRead(threadId)
      .then(() => {
        qc.invalidateQueries({ queryKey: ["conversations", "list"] });
        qc.invalidateQueries({ queryKey: ["conversations", "unread"] });
      })
      .catch(() => {});
  }, [threadId, messages.length, qc]);

  // Auto-scroll to the latest message.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ block: "end" });
  }, [messages.length, threadId]);

  const replyM = useMutation({
    mutationFn: ({ text, files }: { text: string; files: File[] }) =>
      conversationsApi.reply(threadId, { body: text, files }),
    onMutate: async ({ text, files }) => {
      await qc.cancelQueries({ queryKey: msgKey });
      const prev = qc.getQueryData<ThreadData>(msgKey);
      const temp: ConversationMessage = {
        id: -Date.now(),
        direction: "outbound",
        from_email: null,
        to_email: "",
        subject: "",
        body: text,
        body_html: null,
        is_read: true,
        attachments: files.map((f, i) => ({ id: -i - 1, filename: f.name })),
        sent_at: null,
        created_at: new Date().toISOString(),
      };
      qc.setQueryData<ThreadData>(msgKey, (old) => ({
        items: [...(old?.items ?? []), temp],
      }));
      return { prev };
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) qc.setQueryData(msgKey, ctx.prev);
      toast.error("Reply failed to send");
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: msgKey });
      qc.invalidateQueries({ queryKey: ["conversations", "list"] });
    },
  });

  const counterpart =
    messages.find((m) => m.direction === "inbound")?.from_email ||
    messages.find((m) => m.direction === "outbound")?.to_email ||
    "";
  const subject = messages[messages.length - 1]?.subject ?? "";

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* header */}
      <div className="flex shrink-0 items-center gap-2 border-b border-[var(--border)] bg-[var(--surface)] px-3 py-2.5">
        {onBack && (
          <button
            type="button"
            onClick={onBack}
            className="grid h-8 w-8 place-items-center rounded-lg hover:bg-[var(--muted)] md:hidden"
          >
            <ArrowLeft className="h-4 w-4" />
          </button>
        )}
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{counterpart || "Conversation"}</div>
          {subject && (
            <div className="truncate text-xs text-[var(--muted-foreground)]">{subject}</div>
          )}
        </div>
      </div>

      {/* messages */}
      <div className="min-h-0 flex-1 overflow-y-auto bg-[var(--surface-2)] px-3 py-4 sm:px-6">
        {isLoading ? (
          <div className="grid h-full place-items-center text-sm text-[var(--muted-foreground)]">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        ) : (
          <div className="mx-auto flex max-w-3xl flex-col gap-2">
            {messages.map((m) => (
              <MessageBubble key={m.id} m={m} />
            ))}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      <ReplyComposer
        onSend={(text, files) => replyM.mutate({ text, files })}
        disabled={!gmailReady}
        sending={replyM.isPending}
      />
    </div>
  );
}

function MessageBubble({ m }: { m: ConversationMessage }) {
  const out = m.direction === "outbound";
  return (
    <div className={cn("flex", out ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-2xl px-3.5 py-2 text-sm shadow-sm sm:max-w-[70%]",
          out
            ? "rounded-br-sm bg-[var(--color-brand-600)] text-white"
            : "rounded-bl-sm border border-[var(--border)] bg-[var(--surface)] text-[var(--foreground)]",
        )}
      >
        {m.body_html ? (
          <div
            className={cn("chat-html break-words", out && "text-white")}
            // inbound HTML is sanitized server-side; outbound is our own template
            dangerouslySetInnerHTML={{ __html: m.body_html }}
          />
        ) : (
          <div className="whitespace-pre-wrap break-words">{m.body || ""}</div>
        )}

        {m.attachments.length > 0 && (
          <div className="mt-2 flex flex-col gap-1">
            {m.attachments.map((a) => (
              <a
                key={a.id}
                href={a.id > 0 ? conversationsApi.attachmentUrl(a.id) : undefined}
                target="_blank"
                rel="noopener noreferrer"
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs",
                  out ? "bg-white/15 hover:bg-white/25" : "bg-[var(--surface-2)] hover:bg-[var(--muted)]",
                )}
              >
                <FileText className="h-3.5 w-3.5" />
                <span className="truncate">{a.filename}</span>
              </a>
            ))}
          </div>
        )}

        <div className={cn("mt-1 text-[10px]", out ? "text-white/70" : "text-[var(--muted-foreground)]")}>
          {formatDate(m.sent_at || m.created_at)}
        </div>
      </div>
    </div>
  );
}
