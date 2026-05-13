"use client";

import { useMemo, useState } from "react";
import {
  AlertCircle,
  Pause,
  Play,
  Square,
  ExternalLink,
  Trash2,
  Users,
  Filter as FilterIcon,
  CheckCircle2,
  FileSpreadsheet,
  Loader2,
} from "lucide-react";
import { toast } from "sonner";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fundaApi, formatDuration, type ScraperStatus, type PublicationDateOption } from "@/lib/api/funda";
import { PageContainer } from "@/components/page-container";
import { cn, formatNumber } from "@/lib/utils";

const EMPTY_STATUS: ScraperStatus = {
  status: "IDLE",
  total_kvk_stored: 0,
  kvk_collected_this_session: 0,
  total_search_results: 0,
  current_batch: 0,
  properties_scraped: 0,
  properties_filtered: 0,
  properties_failed: 0,
  current_page: 0,
  total_pages_scraped: 0,
  batch_progress: 0,
  active_workers: 0,
  excel_files_created: 0,
  sheets_written: 0,
  valuations_written: 0,
  valuations_failed: 0,
  valuations_pending: 0,
  valuations_fallback: 0,
  elapsed_seconds: 0,
  last_error: "",
  browser_restarts: 0,
  collection_status: "",
  collection_page: 0,
  ids_collected: 0,
  ids_queued: 0,
  duplicate_in_storage: 0,
  duplicate_in_retry_queue: 0,
  consecutive_failures: 0,
};

function statusBadgeClass(s: string): string {
  switch (s) {
    case "RUNNING":
      return "bg-emerald-50 text-emerald-700 border-emerald-200";
    case "PAUSED":
      return "bg-amber-50 text-amber-700 border-amber-200";
    case "STOPPING":
      return "bg-orange-50 text-orange-700 border-orange-200";
    case "COMPLETED":
      return "bg-[var(--color-brand-50)] text-[var(--color-brand-700)] border-[var(--color-brand-200)]";
    case "FAILED":
      return "bg-rose-50 text-rose-700 border-rose-200";
    default:
      return "bg-[var(--muted)] text-[var(--muted-foreground)] border-[var(--border)]";
  }
}

export default function ScraperPage() {
  const qc = useQueryClient();
  // `selectedDateOverride` is null until user picks → falls back to API default.
  const [selectedDateOverride, setSelectedDateOverride] = useState<number | null>(null);
  const [showClearConfirm, setShowClearConfirm] = useState(false);

  const { data: statusData } = useQuery<ScraperStatus>({
    queryKey: ["funda", "status"],
    queryFn: fundaApi.getStatus,
    refetchInterval: 2000,
    refetchIntervalInBackground: true,
  });
  const status = statusData ?? EMPTY_STATUS;

  const { data: optionsData } = useQuery({
    queryKey: ["funda", "publication-options"],
    queryFn: fundaApi.getPublicationDateOptions,
    staleTime: 60_000,
  });
  const options: PublicationDateOption[] = optionsData?.options ?? [
    { value: 5, label: "3-7 Days Ago" },
    { value: 10, label: "8-12 Days Ago" },
    { value: 15, label: "13-17 Days Ago" },
    { value: 30, label: "25-30 Days Ago" },
    { value: 31, label: "30+ Days Ago" },
  ];
  const selectedDate = selectedDateOverride ?? optionsData?.default ?? 5;

  const { data: sheetsData } = useQuery({
    queryKey: ["funda", "sheets-url"],
    queryFn: fundaApi.getSheetsUrl,
    staleTime: 60_000,
  });
  const sheetsUrl = sheetsData?.url ?? "";

  const isRunning = status.status === "RUNNING";
  const isPaused = status.status === "PAUSED";
  const isIdle =
    status.status === "IDLE" || status.status === "COMPLETED" || status.status === "FAILED";

  const onErr = (errPrefix: string) => (e: unknown) => {
    // @ts-expect-error axios shape
    const msg = e?.response?.data?.detail ?? errPrefix;
    toast.error(typeof msg === "string" ? msg : errPrefix);
  };
  const onSuccessInvalidate = () => qc.invalidateQueries({ queryKey: ["funda", "status"] });

  const startM = useMutation({
    mutationFn: () => fundaApi.start(selectedDate),
    onSuccess: onSuccessInvalidate,
    onError: onErr("Failed to start scraper"),
  });
  const stopM = useMutation({
    mutationFn: fundaApi.stop,
    onSuccess: onSuccessInvalidate,
    onError: onErr("Failed to stop scraper"),
  });
  const pauseM = useMutation({
    mutationFn: fundaApi.pause,
    onSuccess: onSuccessInvalidate,
    onError: onErr("Failed to pause scraper"),
  });
  const resumeM = useMutation({
    mutationFn: fundaApi.resume,
    onSuccess: onSuccessInvalidate,
    onError: onErr("Failed to resume scraper"),
  });
  const clearM = useMutation({
    mutationFn: fundaApi.clearKvkStorage,
    onSuccess: onSuccessInvalidate,
    onError: onErr("Failed to clear storage"),
  });

  const anyLoading =
    startM.isPending || stopM.isPending || pauseM.isPending || resumeM.isPending || clearM.isPending;

  const canStart = isIdle && !anyLoading;
  const canStop = (isRunning || isPaused) && !anyLoading;
  const canPause = isRunning && !anyLoading;
  const canResume = isPaused && !anyLoading;

  const elapsedFormatted = useMemo(() => formatDuration(status.elapsed_seconds), [status.elapsed_seconds]);

  return (
    <PageContainer>
      {/* Status bar */}
      <div className="card p-5 md:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div
              className={cn(
                "h-2.5 w-2.5 rounded-full",
                isRunning && "bg-emerald-500 animate-pulse",
                isPaused && "bg-amber-500",
                status.status === "STOPPING" && "bg-orange-500 animate-pulse",
                isIdle && status.status !== "FAILED" && "bg-slate-400",
                status.status === "FAILED" && "bg-rose-500"
              )}
            />
            <span className="text-sm font-medium">Scraper</span>
            <span
              className={cn(
                "rounded-full border px-2.5 py-0.5 text-xs font-semibold",
                statusBadgeClass(status.status)
              )}
            >
              {status.status}
            </span>
          </div>
          <div className="text-xs text-[var(--muted-foreground)]">
            Elapsed <span className="font-mono">{elapsedFormatted}</span>
            {status.active_workers > 0 && <> · {status.active_workers} workers</>}
            {status.collection_status === "collecting" && <> · Collecting page {status.collection_page}</>}
            {status.collection_status === "done" && <> · Collection done</>}
          </div>
        </div>

        {/* Progress */}
        <div className="mt-5">
          <div className="mb-2 flex items-end justify-between">
            <span className="text-xs font-medium text-[var(--muted-foreground)]">Overall progress</span>
            <span className="text-2xl font-semibold text-[var(--color-brand-600)]">
              {status.batch_progress}%
            </span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full bg-[var(--muted)]">
            <div
              className="h-full rounded-full bg-[var(--color-brand-600)] transition-all duration-500"
              style={{ width: `${Math.min(100, Math.max(0, status.batch_progress))}%` }}
            />
          </div>
        </div>

        {/* Stat grid — brand-tone only, no Total Available / Duplicate. */}
        <div className="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <StatTile
            label="Collected"
            value={status.ids_queued > 0 ? formatNumber(status.ids_queued) : "—"}
            sub="new properties"
            tone="brand-soft"
            icon={<Users className="h-4 w-4" />}
          />
          <StatTile
            label="Filtered"
            value={formatNumber(status.properties_filtered)}
            sub="by price"
            tone="brand-soft"
            icon={<FilterIcon className="h-4 w-4" />}
          />
          <StatTile
            label="Google Sheets"
            value={formatNumber(status.sheets_written)}
            sub="rows written"
            tone="brand"
            icon={<FileSpreadsheet className="h-4 w-4" />}
          />
        </div>

        {status.last_error && (
          <div className="mt-5 flex items-start gap-2 rounded-xl border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <strong className="font-semibold">Last error:</strong> {status.last_error}
            </div>
          </div>
        )}
      </div>

      {/* Controls grid */}
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Date selector */}
        <div className="card p-6 lg:col-span-1">
          <h3 className="text-sm font-semibold">Offered Since</h3>
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">Select date range to scrape.</p>
          <select
            value={selectedDate}
            disabled={!isIdle}
            onChange={(e) => setSelectedDateOverride(Number(e.target.value))}
            className="input mt-4 disabled:opacity-60"
          >
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          <p className="mt-3 text-xs text-[var(--muted-foreground)]">
            {selectedDate === 31 && "All properties listed 30+ days ago"}
            {selectedDate === 30 && "Properties listed 25-30 days ago"}
            {selectedDate === 15 && "Properties listed 13-17 days ago"}
            {selectedDate === 10 && "Properties listed 8-12 days ago"}
            {selectedDate === 5 && "Properties listed 3-7 days ago"}
          </p>
        </div>

        {/* Controls */}
        <div className="card p-6 lg:col-span-1">
          <h3 className="text-sm font-semibold">Controls</h3>
          <div className="mt-4 space-y-3">
            <button
              type="button"
              disabled={!canStart}
              onClick={() => startM.mutate()}
              className="btn-primary w-full"
            >
              {startM.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Start
            </button>
            {isPaused ? (
              <button
                type="button"
                disabled={!canResume}
                onClick={() => resumeM.mutate()}
                className="btn-outline w-full"
              >
                {resumeM.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
                Resume
              </button>
            ) : (
              <button
                type="button"
                disabled={!canPause}
                onClick={() => pauseM.mutate()}
                className="btn-outline w-full"
              >
                {pauseM.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Pause className="h-4 w-4" />}
                Pause
              </button>
            )}
            <button
              type="button"
              disabled={!canStop}
              onClick={() => stopM.mutate()}
              className="btn-danger w-full"
            >
              {stopM.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4" />}
              Stop
            </button>
          </div>
        </div>

        {/* Storage + sheets */}
        <div className="card p-6 lg:col-span-1">
          <h3 className="text-sm font-semibold">Storage & Export</h3>
          <div className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--surface-2)] p-4">
            <div className="text-xs text-[var(--muted-foreground)]">Permanent KVK storage</div>
            <div className="mt-1 flex items-baseline justify-between">
              <span className="text-2xl font-semibold">{formatNumber(status.total_kvk_stored)}</span>
              {status.total_kvk_stored > 0 && (
                <button
                  type="button"
                  onClick={() => setShowClearConfirm(true)}
                  className="text-xs font-medium text-rose-600 hover:text-rose-700"
                >
                  <Trash2 className="mr-1 inline h-3 w-3" />
                  Clear
                </button>
              )}
            </div>
            <div className="mt-1 text-xs text-[var(--muted-foreground)]">
              Skipped on future scrapes
            </div>
          </div>

          {sheetsUrl && (
            <a
              href={sheetsUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="btn-outline mt-4 w-full"
            >
              <FileSpreadsheet className="h-4 w-4" />
              Open Google Sheets
              <ExternalLink className="h-3.5 w-3.5" />
            </a>
          )}

          <div className="mt-4 grid grid-cols-3 gap-2 text-center">
            <MiniStat label="Scraped" value={status.properties_scraped} />
            <MiniStat label="Failed" value={status.properties_failed} />
            <MiniStat label="Restarts" value={status.browser_restarts} />
          </div>
        </div>
      </div>

      {/* Clear modal */}
      {showClearConfirm && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4">
          <div className="card w-full max-w-md p-6">
            <div className="flex items-start gap-3">
              <div className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-rose-100">
                <AlertCircle className="h-5 w-5 text-rose-600" />
              </div>
              <div className="min-w-0">
                <h4 className="text-base font-semibold">Clear permanent KVK storage?</h4>
                <p className="mt-1 text-sm text-[var(--muted-foreground)]">
                  This deletes all {formatNumber(status.total_kvk_stored)} stored property IDs. The
                  scraper will start collecting from scratch.
                </p>
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button type="button" className="btn-ghost" onClick={() => setShowClearConfirm(false)}>
                Cancel
              </button>
              <button
                type="button"
                className="btn-danger"
                disabled={clearM.isPending}
                onClick={() => {
                  clearM.mutate(undefined, {
                    onSuccess: () => {
                      toast.success("Storage cleared");
                      setShowClearConfirm(false);
                    },
                  });
                }}
              >
                {clearM.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Trash2 className="h-4 w-4" />}
                Clear all
              </button>
            </div>
          </div>
        </div>
      )}
    </PageContainer>
  );
}

function StatTile({
  label,
  value,
  sub,
  tone,
  icon,
}: {
  label: string;
  value: string;
  sub?: string;
  tone: "brand" | "brand-soft" | "neutral";
  icon?: React.ReactNode;
}) {
  const toneClass =
    tone === "brand"
      ? "bg-[var(--color-brand-600)] text-white"
      : tone === "brand-soft"
      ? "bg-[var(--color-brand-50)] text-[var(--color-brand-700)] dark:bg-[var(--color-brand-900)]/30 dark:text-[var(--color-brand-300)]"
      : "bg-[var(--surface-2)] text-[var(--foreground)]";

  return (
    <div className={cn("rounded-2xl p-4", toneClass)}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium opacity-80">{label}</span>
        {icon && <span className="opacity-70">{icon}</span>}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-[11px] opacity-70">{sub}</div>}
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-[var(--border)] p-3">
      <div className="text-[10px] uppercase tracking-wider text-[var(--muted-foreground)]">{label}</div>
      <div className="mt-0.5 text-sm font-semibold">{formatNumber(value)}</div>
    </div>
  );
}

// Suppress unused-icon warning.
void CheckCircle2;
