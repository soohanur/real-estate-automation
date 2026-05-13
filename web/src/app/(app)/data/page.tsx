"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  Check,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Loader2,
  Mail,
  RefreshCw,
} from "lucide-react";
import { toast } from "sonner";
import {
  propertiesApi,
  type ListParams,
  type Property,
} from "@/lib/api/properties";
import { PageContainer } from "@/components/page-container";
import { EmailModal } from "@/components/email-modal";
import { cn, formatDate, formatNumber } from "@/lib/utils";

const PAGE_SIZE = 50;
const DAY_OPTIONS = [
  { label: "All time", value: 0 },
  { label: "Today", value: 1 },
  { label: "Last 3 days", value: 3 },
  { label: "Last 7 days", value: 7 },
  { label: "Last 30 days", value: 30 },
  { label: "Last 90 days", value: 90 },
];

// Spec: status filter has exactly three options.
const STATUS_OPTIONS = [
  { label: "All status", value: "" },
  { label: "Sent email", value: "sent" },
  { label: "Not sent email", value: "not_sent" },
];

const COLUMNS: Array<{ key: keyof Property; label: string; sortable?: boolean; width?: string }> = [
  { key: "scrape_date", label: "Scrape Date", sortable: true, width: "120px" },
  { key: "address", label: "Address", sortable: true, width: "260px" },
  { key: "asking_price", label: "Asking", sortable: true, width: "110px" },
  { key: "woz_value", label: "WOZ", sortable: true, width: "110px" },
  { key: "suggested_bid", label: "Suggested", sortable: true, width: "120px" },
  { key: "bidding_price", label: "Bidding (edit)", width: "150px" },
  { key: "days_on_market", label: "DOM", sortable: true, width: "70px" },
  { key: "energy_label", label: "Energy", sortable: true, width: "80px" },
  { key: "living_area", label: "m²", width: "70px" },
  { key: "rooms", label: "Rooms", width: "70px" },
  { key: "agency_name", label: "Agency", sortable: true, width: "160px" },
  { key: "agency_email", label: "Agency Email", width: "180px" },
  { key: "email_status", label: "Status", sortable: true, width: "120px" },
];

export default function DataPage() {
  const qc = useQueryClient();
  const [params, setParams] = useState<ListParams>({
    sort: "scrape_date",
    order: "asc", // oldest → newest per spec
    limit: PAGE_SIZE,
    offset: 0,
  });
  const [searchInput, setSearchInput] = useState("");
  const [emailProperty, setEmailProperty] = useState<Property | null>(null);

  // Debounced search → params.q.
  useEffect(() => {
    const t = setTimeout(() => {
      setParams((p) => {
        if ((p.q ?? "") === (searchInput || "")) return p;
        return { ...p, q: searchInput || undefined, offset: 0 };
      });
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  // List — auto-poll for live sync.
  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["properties", "list", params],
    queryFn: () => propertiesApi.list(params),
    placeholderData: (prev) => prev,
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
  });

  // Sync mutation.
  const syncM = useMutation({
    mutationFn: propertiesApi.sync,
    onSuccess: (r) => {
      toast.success(`Synced: ${r.inserted} new, ${r.updated} updated (${r.total_rows} rows)`);
      qc.invalidateQueries({ queryKey: ["properties"] });
    },
    onError: () => toast.error("Sync failed — check backend logs"),
  });

  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / (params.limit ?? PAGE_SIZE)));
  const currentPage = Math.floor((params.offset ?? 0) / (params.limit ?? PAGE_SIZE)) + 1;

  const onSort = (key: string) => {
    setParams((p) => {
      if (p.sort === key) {
        return { ...p, order: p.order === "asc" ? "desc" : "asc", offset: 0 };
      }
      return { ...p, sort: key, order: "asc", offset: 0 };
    });
  };

  const items = data?.items ?? [];
  const showingFrom = items.length > 0 ? (params.offset ?? 0) + 1 : 0;
  const showingTo = (params.offset ?? 0) + items.length;

  return (
    <PageContainer>
      {/* Toolbar */}
      <div className="card mb-4 flex flex-wrap items-center gap-3 p-4">
        <div className="min-w-[260px] flex-1">
          <input
            type="text"
            className="input"
            placeholder="Search address, agency, URL, description…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
        </div>

        <select
          className="input max-w-[180px]"
          value={String(params.days_back ?? 0)}
          onChange={(e) => {
            const v = Number(e.target.value);
            setParams((p) => ({ ...p, days_back: v > 0 ? v : undefined, offset: 0 }));
          }}
        >
          {DAY_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>

        <select
          className="input max-w-[160px]"
          value={params.email_status ?? ""}
          onChange={(e) =>
            setParams((p) => ({ ...p, email_status: e.target.value || undefined, offset: 0 }))
          }
        >
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value || "all"} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>

        <button
          type="button"
          onClick={() => syncM.mutate()}
          disabled={syncM.isPending}
          className="btn-outline"
          title="Pull latest rows from Google Sheet"
        >
          {syncM.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          Sync from Sheet
        </button>
      </div>

      {/* Result summary */}
      <div className="mb-2 flex items-center justify-between text-xs text-[var(--muted-foreground)]">
        <span>
          {isLoading ? "Loading…" : `Showing ${formatNumber(showingFrom)}–${formatNumber(showingTo)} of ${formatNumber(data?.total ?? 0)}`}
          {isFetching && !isLoading ? " · refreshing…" : ""}
        </span>
      </div>

      {/* Table */}
      <div className="card overflow-hidden">
        <div className="max-h-[calc(100vh-260px)] overflow-auto">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-[var(--surface)]">
              <tr className="border-b border-[var(--border)]">
                {COLUMNS.map((c) => (
                  <th
                    key={c.key as string}
                    style={{ minWidth: c.width }}
                    className="px-3 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]"
                  >
                    {c.sortable ? (
                      <button
                        type="button"
                        onClick={() => onSort(c.key as string)}
                        className="inline-flex items-center gap-1 hover:text-[var(--foreground)]"
                      >
                        {c.label}
                        {params.sort === c.key && (
                          params.order === "asc" ? (
                            <ArrowUp className="h-3 w-3" />
                          ) : (
                            <ArrowDown className="h-3 w-3" />
                          )
                        )}
                      </button>
                    ) : (
                      c.label
                    )}
                  </th>
                ))}
                <th
                  className="sticky right-0 bg-[var(--surface)] px-3 py-3 text-right text-[11px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]"
                  style={{ minWidth: "120px" }}
                >
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 && !isLoading && (
                <tr>
                  <td colSpan={COLUMNS.length + 1} className="p-10 text-center text-sm text-[var(--muted-foreground)]">
                    No properties yet. Click <span className="font-medium">Sync from Sheet</span> to import.
                  </td>
                </tr>
              )}
              {items.map((p, idx) => (
                <tr
                  key={p.id}
                  className={cn(
                    "border-b border-[var(--border)] hover:bg-[var(--muted)]",
                    idx % 2 === 1 && "bg-[var(--surface-2)]"
                  )}
                >
                  {COLUMNS.map((c) => (
                    <td key={c.key as string} className="px-3 py-2.5">
                      {c.key === "bidding_price" ? (
                        <BiddingCell property={p} />
                      ) : (
                        renderCell(p, c.key)
                      )}
                    </td>
                  ))}
                  <td className="sticky right-0 bg-[var(--surface)] px-3 py-2.5 text-right">
                    <div className="flex justify-end gap-1">
                      <button
                        type="button"
                        onClick={() => setEmailProperty(p)}
                        className="rounded-lg p-1.5 text-[var(--color-brand-600)] hover:bg-[var(--color-brand-50)]"
                        title="Send email"
                      >
                        <Mail className="h-4 w-4" />
                      </button>
                      <Link
                        href={`/data/${p.id}`}
                        className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
                        title="View profile"
                      >
                        <ExternalLink className="h-4 w-4" />
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between border-t border-[var(--border)] px-4 py-3 text-sm">
          <span className="text-[var(--muted-foreground)]">
            Page {currentPage} of {totalPages}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              className="btn-outline"
              disabled={(params.offset ?? 0) <= 0 || isFetching}
              onClick={() =>
                setParams((p) => ({
                  ...p,
                  offset: Math.max(0, (p.offset ?? 0) - (p.limit ?? PAGE_SIZE)),
                }))
              }
            >
              <ChevronLeft className="h-4 w-4" />
              Prev
            </button>
            <button
              type="button"
              className="btn-outline"
              disabled={currentPage >= totalPages || isFetching}
              onClick={() =>
                setParams((p) => ({
                  ...p,
                  offset: (p.offset ?? 0) + (p.limit ?? PAGE_SIZE),
                }))
              }
            >
              Next
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      <EmailModal property={emailProperty} open={!!emailProperty} onClose={() => setEmailProperty(null)} />
    </PageContainer>
  );
}

/**
 * Inline editable bidding-price cell. Saves to backend on Enter or blur,
 * with a small Check button so user sees the explicit save action.
 */
function BiddingCell({ property }: { property: Property }) {
  const qc = useQueryClient();
  const [value, setValue] = useState<string>(property.bidding_price ?? "");
  const [original, setOriginal] = useState<string>(property.bidding_price ?? "");

  // Sync if backend value changes (e.g. another tab edited it). setState in
  // effect here is the documented React 19 sync-from-prop pattern.
  useEffect(() => {
    const v = property.bidding_price ?? "";
    if (v !== original) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setOriginal(v);
      setValue(v);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [property.bidding_price]);

  const saveM = useMutation({
    mutationFn: (v: string) => propertiesApi.update(property.id, { bidding_price: v }),
    onSuccess: (updated) => {
      setOriginal(updated.bidding_price ?? "");
      qc.invalidateQueries({ queryKey: ["properties"] });
      toast.success("Bidding price saved");
    },
    onError: () => toast.error("Save failed"),
  });

  const dirty = value !== original;

  return (
    <div className="flex items-center gap-1">
      <input
        type="text"
        inputMode="numeric"
        className="input h-8 w-full px-2 py-1 text-sm"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            if (dirty) saveM.mutate(value);
          }
          if (e.key === "Escape") setValue(original);
        }}
        placeholder="€ —"
      />
      {dirty && (
        <button
          type="button"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-[var(--color-brand-600)] text-white hover:bg-[var(--color-brand-700)]"
          onClick={() => saveM.mutate(value)}
          disabled={saveM.isPending}
          title="Save"
        >
          {saveM.isPending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
        </button>
      )}
    </div>
  );
}

function renderCell(p: Property, key: keyof Property) {
  const v = p[key];
  if (v === null || v === undefined || v === "") return <span className="text-[var(--muted-foreground)]">—</span>;

  if (key === "email_status") {
    return <StatusChip status={String(v)} />;
  }
  if (key === "scrape_date") {
    return <span className="text-xs text-[var(--muted-foreground)]">{String(v)}</span>;
  }
  if (key === "address") {
    return <span className="font-medium">{String(v)}</span>;
  }
  return <span>{String(v)}</span>;
}

function StatusChip({ status }: { status: string }) {
  const tone =
    status === "sent"
      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
      : status === "failed"
      ? "bg-rose-50 text-rose-700 border-rose-200"
      : status === "queued"
      ? "bg-amber-50 text-amber-700 border-amber-200"
      : "bg-[var(--muted)] text-[var(--muted-foreground)] border-[var(--border)]";
  return (
    <span className={cn("inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium", tone)}>
      {status}
    </span>
  );
}

// Suppress unused import warnings.
void formatDate;
