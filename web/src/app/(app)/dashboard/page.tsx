"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCircle2,
  Clock,
  Database,
  Mail,
  Send,
  AlertCircle,
  TrendingUp,
} from "lucide-react";
import { dashboardApi } from "@/lib/api/dashboard";
import { PageContainer } from "@/components/page-container";
import { EmailReportChart } from "@/components/email-report-chart";
import { cn, formatNumber } from "@/lib/utils";

export default function DashboardPage() {
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard", "stats"],
    queryFn: dashboardApi.stats,
    // Backend auto-syncs Sheet→DB every 30s; faster polling can't show
    // fresher data, just churns re-renders.
    refetchInterval: 30_000,
  });

  return (
    <PageContainer>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <StatCard
          href="/emails"
          label="Total emails sent"
          value={formatNumber(data?.emails_sent ?? 0)}
          icon={<CheckCircle2 className="h-4 w-4" />}
          tone="emerald"
          loading={isLoading}
        />
        <StatCard
          href="/emails"
          label="Sent today"
          value={formatNumber(data?.emails_sent_today ?? 0)}
          icon={<Send className="h-4 w-4" />}
          tone="brand"
          loading={isLoading}
        />
        <StatCard
          href="/data"
          label="Total scraped"
          value={formatNumber(data?.total_scraped ?? 0)}
          icon={<Database className="h-4 w-4" />}
          tone="indigo"
          loading={isLoading}
        />
        <StatCard
          href="/data?email_status=not_sent"
          label="Not emailed yet"
          value={formatNumber(data?.not_emailed ?? 0)}
          icon={<Mail className="h-4 w-4" />}
          tone="amber"
          loading={isLoading}
        />
        <StatCard
          href="/data?days_back=1"
          label="Scraped today"
          value={formatNumber(data?.scraped_today ?? 0)}
          icon={<TrendingUp className="h-4 w-4" />}
          tone="brand"
          loading={isLoading}
        />
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <MiniCard label="Email queued" value={data?.emails_queued ?? 0} icon={<Clock className="h-4 w-4" />} />
        <MiniCard label="Email failed" value={data?.emails_failed ?? 0} icon={<AlertCircle className="h-4 w-4" />} />
        <MiniCard label="Total emails" value={data?.total_emails ?? 0} icon={<Mail className="h-4 w-4" />} />
      </div>

      <EmailReportChart className="mt-6" />
    </PageContainer>
  );
}

function StatCard({
  href,
  label,
  value,
  icon,
  tone,
  loading,
}: {
  href: string;
  label: string;
  value: string;
  icon: React.ReactNode;
  tone: "brand" | "emerald" | "amber" | "indigo";
  loading?: boolean;
}) {
  const toneIcon =
    tone === "brand"
      ? "bg-[var(--color-brand-50)] text-[var(--color-brand-700)]"
      : tone === "emerald"
      ? "bg-emerald-50 text-emerald-700"
      : tone === "amber"
      ? "bg-amber-50 text-amber-700"
      : "bg-indigo-50 text-indigo-700";
  return (
    <Link
      href={href}
      className="card group relative flex items-center justify-between p-5 transition-all hover:-translate-y-0.5 hover:shadow-md"
    >
      <div>
        <div className="text-xs font-medium text-[var(--muted-foreground)]">{label}</div>
        <div className="mt-1 text-2xl font-semibold tabular-nums">
          {loading ? <span className="text-[var(--muted-foreground)]">…</span> : value}
        </div>
      </div>
      <div className={cn("grid h-10 w-10 place-items-center rounded-xl", toneIcon)}>{icon}</div>
      <ArrowRight className="absolute right-3 top-3 h-3.5 w-3.5 opacity-0 transition-opacity group-hover:opacity-100" />
    </Link>
  );
}

function MiniCard({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) {
  return (
    <div className="card flex items-center justify-between p-4">
      <div>
        <div className="text-xs font-medium text-[var(--muted-foreground)]">{label}</div>
        <div className="mt-0.5 text-xl font-semibold tabular-nums">{formatNumber(value)}</div>
      </div>
      <div className="grid h-9 w-9 place-items-center rounded-xl bg-[var(--surface-2)] text-[var(--muted-foreground)]">
        {icon}
      </div>
    </div>
  );
}
