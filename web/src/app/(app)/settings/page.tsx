"use client";

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, AlertCircle, Mail, RefreshCw, Inbox, Send } from "lucide-react";
import { emailsApi } from "@/lib/api/emails";
import { PageContainer } from "@/components/page-container";
import { formatDate } from "@/lib/utils";

export default function SettingsPage() {
  const { data: gmail, isLoading } = useQuery({
    queryKey: ["gmail", "status"],
    queryFn: emailsApi.gmailStatus,
    refetchInterval: 30_000,
  });

  const connected = gmail?.connected === true;
  const readEnabled = gmail?.read_enabled === true;
  const connectUrl = emailsApi.gmailConnectUrl();

  return (
    <PageContainer>
      <div className="card p-5 md:p-6">
        <h1 className="text-xl font-semibold md:text-2xl">Settings</h1>
        <p className="mt-1 text-sm text-[var(--muted-foreground)]">
          Connect the mailbox used to send bids and receive agency replies.
        </p>
      </div>

      <div className="card mt-4 p-5 md:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-[var(--surface-2)]">
              <Mail className="h-5 w-5 text-[var(--color-brand-600)]" />
            </div>
            <div>
              <h2 className="text-base font-semibold">Gmail</h2>
              <p className="text-sm text-[var(--muted-foreground)]">
                {isLoading
                  ? "Checking…"
                  : gmail?.email_address || "No mailbox configured (set GMAIL_SENDER)"}
              </p>
              {connected && gmail?.last_updated && (
                <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
                  Connected {formatDate(gmail.last_updated)}
                </p>
              )}
            </div>
          </div>

          <a
            href={connectUrl}
            className="inline-flex items-center gap-2 rounded-lg bg-[var(--color-brand-600)] px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
          >
            <RefreshCw className="h-4 w-4" />
            {connected ? "Reconnect Gmail" : "Connect Gmail"}
          </a>
        </div>

        {/* Capability rows — sending works with gmail.send; the chat inbox
            also needs gmail.readonly, which requires a reconnect. */}
        <div className="mt-5 grid gap-3 sm:grid-cols-2">
          <Capability
            ok={connected}
            icon={<Send className="h-4 w-4" />}
            title="Sending"
            okText="Bids can be sent"
            badText="Connect Gmail to send bids"
          />
          <Capability
            ok={connected && readEnabled}
            icon={<Inbox className="h-4 w-4" />}
            title="Receiving replies"
            okText="Agency replies sync to the chat inbox"
            badText="Reconnect and grant read access"
          />
        </div>

        {connected && !readEnabled && (
          <div className="mt-4 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <span>
              Read access isn&apos;t granted yet, so incoming replies won&apos;t appear in
              Emails. Click <b>Reconnect Gmail</b> and approve the read permission.
            </span>
          </div>
        )}

        {!connected && !isLoading && (
          <p className="mt-4 text-xs text-[var(--muted-foreground)]">
            Sign in as the shared mailbox. Google only issues a refresh token on first
            consent — if it fails, remove the app under Google Account → Third-party
            access and try again.
          </p>
        )}
      </div>
    </PageContainer>
  );
}

function Capability({
  ok,
  icon,
  title,
  okText,
  badText,
}: {
  ok: boolean;
  icon: React.ReactNode;
  title: string;
  okText: string;
  badText: string;
}) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-3">
      <div className="mt-0.5 text-[var(--muted-foreground)]">{icon}</div>
      <div className="min-w-0">
        <div className="flex items-center gap-1.5 text-sm font-medium">
          {title}
          {ok ? (
            <CheckCircle2 className="h-4 w-4 text-emerald-500" />
          ) : (
            <AlertCircle className="h-4 w-4 text-amber-500" />
          )}
        </div>
        <p className="text-xs text-[var(--muted-foreground)]">{ok ? okText : badText}</p>
      </div>
    </div>
  );
}
