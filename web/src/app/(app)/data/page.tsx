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

// Infinite scroll: page size = 100 rows. Each page is a small JSON
// payload (~150KB compact) so memory + CPU + DB stay flat regardless
// of total dataset size — works the same at 3k or 1M rows.
const PAGE_SIZE = 100;

const TAB_OPTIONS = [
  "3-7 Days Ago",
  "8-12 Days Ago",
  "13-17 Days Ago",
  "25-30 Days Ago",
  "30+ Days Ago",
];

const STATUS_OPTIONS = [
  { label: "All status", value: "" },
  { label: "Sent email", value: "sent" },
  { label: "Not sent email", value: "not_sent" },
];

// Filter slice — everything except limit/offset (those are infinite-query
// internals). Changing any of these resets pagination back to page 0.
type Filters = Pick<ListParams, "q" | "sheet_tab" | "email_status" | "sort" | "order">;

export default function DataPage() {
  const qc = useQueryClient();
  const [filters, setFilters] = useState<Filters>({
    sort: "scrape_date",
    order: "asc",
  });
  const [searchInput, setSearchInput] = useState("");
  const [emailProperty, setEmailProperty] = useState<Property | null>(null);

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
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });

  // Flatten loaded pages into one items array for the virtualizer.
  const items: Property[] = useMemo(
    () => (data?.pages ?? []).flatMap((p) => p.items as Property[]),
    [data],
  );
  const total = data?.pages[0]?.total ?? 0;

  const syncM = useMutation({
    mutationFn: propertiesApi.sync,
    onSuccess: (r) => {
      toast.success(`Synced: ${r.inserted} new, ${r.updated} updated (${r.total_rows} rows)`);
      qc.invalidateQueries({ queryKey: ["properties"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: () => toast.error("Sync failed — check backend logs"),
  });

  const onSort = (key: string) => {
    setFilters((f) => {
      if (f.sort === key) {
        return { ...f, order: f.order === "asc" ? "desc" : "asc" };
      }
      return { ...f, sort: key, order: "asc" };
    });
  };

  return (
    <PageContainer fill>
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

        <select
          className="input max-w-[200px]"
          value={filters.sheet_tab ?? ""}
          onChange={(e) =>
            setFilters((f) => ({ ...f, sheet_tab: e.target.value || undefined }))
          }
        >
          <option value="">All time</option>
          {TAB_OPTIONS.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>

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
          {isFetchingNextPage ? " · loading next 100…" : ""}
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
        // Infinite scroll wiring — the virtualizer fires onLoadMore when
        // the user scrolls within ~10 rows of the end of the loaded set.
        onLoadMore={() => {
          if (hasNextPage && !isFetchingNextPage) fetchNextPage();
        }}
        hasMore={!!hasNextPage}
        isLoadingMore={isFetchingNextPage}
      />

      <EmailModal property={emailProperty} open={!!emailProperty} onClose={() => setEmailProperty(null)} />
    </PageContainer>
  );
}
