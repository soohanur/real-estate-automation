"use client";

/**
 * EmailReportChart — stacked bar graph of email_messages over time
 * (sent / queued / failed). Preset windows + custom date range.
 *
 * Data source: GET /api/v1/dashboard/email-report which buckets by
 * day / month / year based on the requested period.
 */
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Loader2 } from "lucide-react";
import {
  dashboardApi,
  type EmailReport,
  type EmailReportPeriod,
} from "@/lib/api/dashboard";
import { cn, formatNumber } from "@/lib/utils";

const PRESETS: { label: string; value: EmailReportPeriod }[] = [
  { label: "Day",    value: "day" },
  { label: "Week",   value: "week" },
  { label: "Month",  value: "month" },
  { label: "Year",   value: "year" },
  { label: "All",    value: "all" },
  { label: "Custom", value: "custom" },
];

const SERIES = [
  { key: "sent",   color: "var(--color-brand-600)", label: "Sent" },
  { key: "queued", color: "#f59e0b",                 label: "Queued" },
  { key: "failed", color: "#e11d48",                 label: "Failed" },
] as const;

export function EmailReportChart({ className }: { className?: string }) {
  const [period, setPeriod] = useState<EmailReportPeriod>("month");
  const [fromDate, setFromDate] = useState<string>("");
  const [toDate, setToDate] = useState<string>("");

  const queryArgs = useMemo(() => {
    if (period === "custom") {
      // Only fire when both dates set — otherwise the request returns 400.
      if (!fromDate || !toDate) return null;
      return { period, from_date: fromDate, to_date: toDate };
    }
    return { period };
  }, [period, fromDate, toDate]);

  const { data, isLoading, isFetching, error } = useQuery<EmailReport>({
    queryKey: ["dashboard", "email-report", queryArgs],
    queryFn: () => dashboardApi.emailReport(queryArgs!),
    enabled: queryArgs !== null,
    refetchInterval: 30_000,
  });

  const buckets = data?.buckets ?? [];
  const totals = data?.totals;

  return (
    <div className={cn("card flex min-h-0 flex-col p-5", className)}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold">Emails sent over time</h3>
          {data && (
            <p className="mt-0.5 text-xs text-[var(--muted-foreground)]">
              {data.from_date} → {data.to_date} · grouped by {data.granularity}
              {totals && totals.total > 0 && (
                <>
                  {" · "}
                  <span className="text-emerald-700">{formatNumber(totals.sent)} sent</span>
                  {" · "}
                  <span className="text-amber-700">{formatNumber(totals.queued)} queued</span>
                  {" · "}
                  <span className="text-rose-700">{formatNumber(totals.failed)} failed</span>
                </>
              )}
            </p>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="flex overflow-hidden rounded-lg border border-[var(--border)] bg-[var(--surface)]">
            {PRESETS.map((p) => (
              <button
                key={p.value}
                type="button"
                onClick={() => setPeriod(p.value)}
                className={cn(
                  "px-3 py-1.5 text-xs font-medium transition-colors",
                  p.value === period
                    ? "bg-[var(--color-brand-600)] text-white"
                    : "text-[var(--muted-foreground)] hover:bg-[var(--muted)]",
                )}
              >
                {p.label}
              </button>
            ))}
          </div>

          {period === "custom" && (
            <div className="flex items-center gap-1">
              <input
                type="date"
                value={fromDate}
                onChange={(e) => setFromDate(e.target.value)}
                className="input h-9 w-36 text-sm"
              />
              <span className="text-xs text-[var(--muted-foreground)]">→</span>
              <input
                type="date"
                value={toDate}
                onChange={(e) => setToDate(e.target.value)}
                className="input h-9 w-36 text-sm"
              />
            </div>
          )}

          {isFetching && (
            <Loader2 className="h-4 w-4 animate-spin text-[var(--muted-foreground)]" />
          )}
        </div>
      </div>

      <div className="mt-4 min-h-[280px] flex-1">
        {error ? (
          <div className="grid h-full place-items-center text-sm text-rose-700">
            Failed to load email report
          </div>
        ) : period === "custom" && queryArgs === null ? (
          <div className="grid h-full place-items-center text-sm text-[var(--muted-foreground)]">
            Pick a start and end date
          </div>
        ) : isLoading || !data ? (
          <div className="grid h-full place-items-center text-sm text-[var(--muted-foreground)]">
            Loading…
          </div>
        ) : totals && totals.total === 0 ? (
          <div className="grid h-full place-items-center text-sm text-[var(--muted-foreground)]">
            No emails in this range
          </div>
        ) : (
          <ResponsiveContainer width="100%" height={320}>
            <BarChart data={buckets} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" vertical={false} />
              <XAxis
                dataKey="bucket"
                tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                interval="preserveStartEnd"
              />
              <YAxis
                tick={{ fontSize: 11, fill: "var(--muted-foreground)" }}
                allowDecimals={false}
                width={36}
              />
              <Tooltip
                cursor={{ fill: "rgba(0,0,0,0.05)" }}
                contentStyle={{
                  background: "var(--surface)",
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  fontSize: 12,
                }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {SERIES.map((s) => (
                <Bar
                  key={s.key}
                  dataKey={s.key}
                  name={s.label}
                  stackId="emails"
                  fill={s.color}
                  radius={[2, 2, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  );
}
