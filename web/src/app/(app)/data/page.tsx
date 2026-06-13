"use client";

import { useEffect, useMemo, useState } from "react";
import {
  useInfiniteQuery,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import {
  propertiesApi,
  type ListParams,
  type Property,
  type PropertyList,
} from "@/lib/api/properties";
import { PageContainer } from "@/components/page-container";
import { EmailModal } from "@/components/email-modal";
import { PropertiesTable } from "@/components/properties-table";
import { formatNumber } from "@/lib/utils";

// Infinite scroll: page size = 30 rows. Tiny pages keep first paint
// near-instant and the fetch cadence smooth as the user scrolls.
const PAGE_SIZE = 30;

const STATUS_OPTIONS = [
  { label: "All status", value: "" },
  { label: "Sent email", value: "sent" },
  { label: "Queued email", value: "queued" },
  { label: "Failed email", value: "failed" },
  { label: "Not sent email", value: "not_sent" },
];

// Days-on-market presets — pick a range with one click. "Custom"
// exposes min + max inputs (set min === max for "exactly N days").
const DOM_PRESETS = [
  { label: "All",          min: undefined as number | undefined, max: undefined as number | undefined },
  { label: "Today",        min: 0, max: 0 },
  { label: "≤ 3 days",     min: 0, max: 3 },
  { label: "≤ 7 days",     min: 0, max: 7 },
  { label: "8–14 days",    min: 8, max: 14 },
  { label: "15–30 days",   min: 15, max: 30 },
  { label: "30+ days",     min: 30, max: undefined },
  { label: "Custom",       min: undefined, max: undefined },
];

type Filters = Pick<
  ListParams,
  "q" | "sheet_tab" | "email_status" | "sort" | "order" | "dom_min" | "dom_max"
>;

export default function DataPage() {
  const qc = useQueryClient();
  const [filters, setFilters] = useState<Filters>({
    sort: "display_order",
    order: "asc",
    email_status: "not_sent",
  });
  const [searchInput, setSearchInput] = useState("");
  const [emailProperty, setEmailProperty] = useState<Property | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<Property | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [confirmBulk, setConfirmBulk] = useState(false);

  // DOM custom-range inputs — live behind the "Custom" preset so we
  // don't push a request on every keystroke until the user explicitly
  // chooses Custom.
  const [domPresetIdx, setDomPresetIdx] = useState(0);
  const [customMin, setCustomMin] = useState<string>("");
  const [customMax, setCustomMax] = useState<string>("");

  // Debounced search → filters.q.
  useEffect(() => {
    const t = setTimeout(() => {
      setFilters((f) => {
        if ((f.q ?? "") === (searchInput || "")) return f;
        return { ...f, q: searchInput || undefined };
      });
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  // Apply DOM preset → filters whenever the preset OR (in Custom mode)
  // the typed bounds change.
  useEffect(() => {
    const preset = DOM_PRESETS[domPresetIdx];
    let next_min: number | undefined;
    let next_max: number | undefined;
    if (preset.label === "Custom") {
      const a = customMin.trim() === "" ? undefined : Number(customMin);
      const b = customMax.trim() === "" ? undefined : Number(customMax);
      next_min = Number.isFinite(a) ? (a as number) : undefined;
      next_max = Number.isFinite(b) ? (b as number) : undefined;
    } else {
      next_min = preset.min;
      next_max = preset.max;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFilters((f) => {
      if (f.dom_min === next_min && f.dom_max === next_max) return f;
      return { ...f, dom_min: next_min, dom_max: next_max };
    });
  }, [domPresetIdx, customMin, customMax]);

  const {
    data,
    isLoading,
    isFetching,
    isFetchingNextPage,
    fetchNextPage,
    hasNextPage,
  } = useInfiniteQuery<PropertyList, Error>({
    queryKey: ["properties", "list", filters],
    initialPageParam: 0,
    queryFn: ({ pageParam }) =>
      propertiesApi.list({
        ...filters,
        limit: PAGE_SIZE,
        offset: pageParam as number,
      }),
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((acc, p) => acc + p.items.length, 0);
      return loaded < lastPage.total ? loaded : undefined;
    },
    placeholderData: (prev) => prev,
    // No polling — fresh data only on:
    //   - page mount / route entry (default React Query behaviour)
    //   - explicit Sync from Sheet button click (invalidates this key)
    //   - filter / sort change (queryKey includes filters)
    // Auto-refresh while user edits caused rows to shuffle and
    // bidding inputs to lose context — disabled.
    refetchInterval: false,
    refetchOnMount: true,
    refetchOnWindowFocus: false,
  });

  // Flatten loaded pages + dedup-by-id (offset pagination races the
  // 30s auto-sync → same DB row can appear in two pages → duplicate
  // React keys → virtualizer overlap. Keep first occurrence.)
  const items: Property[] = useMemo(() => {
    const all = (data?.pages ?? []).flatMap((p) => p.items as Property[]);
    const seen = new Set<number>();
    const out: Property[] = [];
    for (const p of all) {
      if (seen.has(p.id)) continue;
      seen.add(p.id);
      out.push(p);
    }
    return out;
  }, [data]);
  const total = data?.pages[0]?.total ?? 0;

  const allSelected = items.length > 0 && items.every((p) => selected.has(p.id));
  const toggleAll = () =>
    setSelected((prev) =>
      items.length > 0 && items.every((p) => prev.has(p.id))
        ? new Set()
        : new Set(items.map((p) => p.id)),
    );

  const syncM = useMutation({
    mutationFn: propertiesApi.sync,
    onSuccess: (r) => {
      toast.success(`Synced: ${r.inserted} new, ${r.updated} updated (${r.total_rows} rows)`);
      qc.invalidateQueries({ queryKey: ["properties"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: () => toast.error("Sync failed — check backend logs"),
  });

  const deleteM = useMutation({
    mutationFn: (id: number) => propertiesApi.remove(id),
    onSuccess: (r) => {
      toast.success(
        `Property deleted${r.sheet_deleted ? " (sheet + database)" : " (database only — sheet row not found)"}.`,
      );
      setConfirmDelete(null);
      qc.invalidateQueries({ queryKey: ["properties"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: () => toast.error("Delete failed — check backend logs"),
  });

  const bulkDeleteM = useMutation({
    mutationFn: (ids: number[]) => propertiesApi.bulkRemove(ids),
    onSuccess: (r) => {
      toast.success(`Deleted ${r.deleted} properties (sheet ${r.sheet_deleted}, KVK ${r.kvk_removed}).`);
      setSelected(new Set());
      setConfirmBulk(false);
      qc.invalidateQueries({ queryKey: ["properties"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: () => toast.error("Bulk delete failed — check backend logs"),
  });

  const toggleSelect = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const onSort = (key: string) => {
    setFilters((f) => {
      if (f.sort === key) {
        return { ...f, order: f.order === "asc" ? "desc" : "asc" };
      }
      return { ...f, sort: key, order: "asc" };
    });
  };

  const isCustomDom = DOM_PRESETS[domPresetIdx].label === "Custom";

  return (
    <PageContainer>
      <div className="card mb-4 flex shrink-0 flex-wrap items-center gap-3 p-4">
        <div className="min-w-[260px] flex-1">
          <input
            type="text"
            className="input"
            placeholder="Search address, agency, URL, description…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
          />
        </div>

        {/* DOM preset — replaces the old sheet-tab time filter (hidden
            but kept in API so existing requests still work). */}
        <select
          className="input max-w-[200px]"
          value={domPresetIdx}
          onChange={(e) => setDomPresetIdx(Number(e.target.value))}
          title="Filter by days on market (dynamic — listed_since to today)"
        >
          {DOM_PRESETS.map((p, i) => (
            <option key={p.label} value={i}>
              {p.label}
            </option>
          ))}
        </select>

        {isCustomDom && (
          <div className="flex items-center gap-1">
            <input
              type="number"
              min={0}
              placeholder="min"
              value={customMin}
              onChange={(e) => setCustomMin(e.target.value)}
              className="input h-9 w-20 text-sm"
            />
            <span className="text-xs text-[var(--muted-foreground)]">→</span>
            <input
              type="number"
              min={0}
              placeholder="max"
              value={customMax}
              onChange={(e) => setCustomMax(e.target.value)}
              className="input h-9 w-20 text-sm"
            />
            <span className="text-[10px] text-[var(--muted-foreground)]">days</span>
          </div>
        )}

        <select
          className="input max-w-[160px]"
          value={filters.email_status ?? ""}
          onChange={(e) =>
            setFilters((f) => ({ ...f, email_status: e.target.value || undefined }))
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

      <div className="mb-2 flex shrink-0 items-center justify-between text-xs text-[var(--muted-foreground)]">
        <span>
          {isLoading
            ? "Loading…"
            : `${formatNumber(items.length)} of ${formatNumber(total)} properties`}
          {isFetching && !isLoading && !isFetchingNextPage ? " · refreshing…" : ""}
          {isFetchingNextPage ? " · loading next 30…" : ""}
          {!hasNextPage && items.length > 0 ? " · all loaded" : ""}
        </span>
      </div>

      <PropertiesTable
        className="flex-1"
        items={items}
        isLoading={isLoading}
        isFetching={isFetching}
        emptyMessage={
          <>
            No properties match the filters. Click <span className="font-medium">Sync from Sheet</span> to import.
          </>
        }
        sort={filters.sort}
        order={filters.order}
        onSort={onSort}
        onEmail={(p) => setEmailProperty(p as Property)}
        onDelete={(p) => setConfirmDelete(p as Property)}
        selectedIds={selected}
        onToggleSelect={toggleSelect}
        onToggleAll={toggleAll}
        allSelected={allSelected}
        onLoadMore={() => {
          if (hasNextPage && !isFetchingNextPage) fetchNextPage();
        }}
        hasMore={!!hasNextPage}
        isLoadingMore={isFetchingNextPage}
      />

      {/* Bulk action bar — floats when rows are selected. */}
      {selected.size > 0 && (
        <div className="fixed bottom-6 left-1/2 z-40 flex -translate-x-1/2 items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-2.5 shadow-lg">
          <span className="text-sm font-medium">{selected.size} selected</span>
          <button type="button" className="btn-ghost text-xs" onClick={() => setSelected(new Set())}>
            Clear
          </button>
          <button
            type="button"
            onClick={() => setConfirmBulk(true)}
            className="inline-flex items-center gap-1.5 rounded-md bg-rose-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-rose-700"
          >
            Delete selected ({selected.size})
          </button>
        </div>
      )}

      {confirmBulk && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4">
          <div className="card w-full max-w-md p-5">
            <h3 className="text-base font-semibold">Delete {selected.size} properties?</h3>
            <p className="mt-2 text-xs text-[var(--muted-foreground)]">
              This permanently removes {selected.size} rows from <b>the Google Sheet, the database, and KVK storage</b> (they won&apos;t be re-scraped). This cannot be undone.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                className="btn-ghost"
                onClick={() => setConfirmBulk(false)}
                disabled={bulkDeleteM.isPending}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => bulkDeleteM.mutate([...selected])}
                disabled={bulkDeleteM.isPending}
                className="inline-flex items-center gap-2 rounded-md bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
              >
                {bulkDeleteM.isPending ? "Deleting…" : `Yes, delete ${selected.size}`}
              </button>
            </div>
          </div>
        </div>
      )}

      <EmailModal property={emailProperty} open={!!emailProperty} onClose={() => setEmailProperty(null)} />

      {confirmDelete && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4">
          <div className="card w-full max-w-md p-5">
            <h3 className="text-base font-semibold">Delete this property?</h3>
            <p className="mt-2 text-sm text-[var(--muted-foreground)]">
              {confirmDelete.address || confirmDelete.url}
            </p>
            <p className="mt-2 text-xs text-[var(--muted-foreground)]">
              This permanently removes the row from <b>both the Google Sheet and the database</b>. This cannot be undone.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                className="btn-ghost"
                onClick={() => setConfirmDelete(null)}
                disabled={deleteM.isPending}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => deleteM.mutate(confirmDelete.id)}
                disabled={deleteM.isPending}
                className="inline-flex items-center gap-2 rounded-md bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700 disabled:opacity-50"
              >
                {deleteM.isPending ? "Deleting…" : "Yes, delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </PageContainer>
  );
}
