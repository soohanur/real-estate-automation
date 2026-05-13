"use client";

import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import {
  propertiesApi,
  type ListParams,
  type Property,
} from "@/lib/api/properties";
import { PageContainer } from "@/components/page-container";
import { EmailModal } from "@/components/email-modal";
import { PropertiesTable } from "@/components/properties-table";
import { formatNumber } from "@/lib/utils";

// No pagination — single scrollable list. Backend cap is 1000.
const LIST_LIMIT = 1000;

// Sheet tab dropdown is fixed — always all five buckets, regardless of
// whether the DB has rows for each one yet.
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

export default function DataPage() {
  const qc = useQueryClient();
  const [params, setParams] = useState<ListParams>({
    sort: "scrape_date",
    order: "asc",
    limit: LIST_LIMIT,
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

  const { data, isLoading, isFetching } = useQuery({
    queryKey: ["properties", "list", params],
    queryFn: () => propertiesApi.list(params),
    placeholderData: (prev) => prev,
    refetchInterval: 10_000,
    refetchIntervalInBackground: false,
  });

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
    setParams((p) => {
      if (p.sort === key) {
        return { ...p, order: p.order === "asc" ? "desc" : "asc", offset: 0 };
      }
      return { ...p, sort: key, order: "asc", offset: 0 };
    });
  };

  const items = data?.items ?? [];

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
          value={params.sheet_tab ?? ""}
          onChange={(e) =>
            setParams((p) => ({ ...p, sheet_tab: e.target.value || undefined, offset: 0 }))
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

      <div className="mb-2 flex shrink-0 items-center justify-between text-xs text-[var(--muted-foreground)]">
        <span>
          {isLoading
            ? "Loading…"
            : `${formatNumber(items.length)} of ${formatNumber(data?.total ?? 0)} properties`}
          {isFetching && !isLoading ? " · refreshing…" : ""}
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
        sort={params.sort}
        order={params.order}
        onSort={onSort}
        onEmail={(p) => setEmailProperty(p as Property)}
      />

      <EmailModal property={emailProperty} open={!!emailProperty} onClose={() => setEmailProperty(null)} />
    </PageContainer>
  );
}
