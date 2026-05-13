"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowDown,
  ArrowUp,
  Check,
  ExternalLink,
  Loader2,
  Mail,
} from "lucide-react";
import { toast } from "sonner";
import { propertiesApi, type Property } from "@/lib/api/properties";
import { cn } from "@/lib/utils";

/**
 * Row shape consumed by the table. Wider than Property so Dashboard's
 * LatestProperty can plug in without coercion.
 */
export type PropertiesTableRow = {
  id: number;
  url: string;
  scrape_date?: string | null;
  address?: string | null;
  asking_price?: string | null;
  woz_value?: string | null;
  suggested_bid?: string | null;
  bidding_price?: string | null;
  days_on_market?: string | null;
  energy_label?: string | null;
  living_area?: string | null;
  rooms?: string | null;
  agency_name?: string | null;
  agency_email?: string | null;
  sheet_tab?: string | null;
  email_status?: string | null;
};

const COLUMNS: Array<{
  key: keyof PropertiesTableRow;
  label: string;
  sortable?: boolean;
  width?: string;
}> = [
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
  { key: "sheet_tab", label: "Range", width: "130px" },
  { key: "agency_name", label: "Agency", sortable: true, width: "160px" },
  { key: "agency_email", label: "Agency Email", width: "180px" },
  { key: "email_status", label: "Status", sortable: true, width: "120px" },
];

export function PropertiesTable({
  items,
  isLoading,
  isFetching,
  emptyMessage,
  sort,
  order,
  onSort,
  onEmail,
  showBiddingEdit = true,
  className,
}: {
  items: PropertiesTableRow[];
  isLoading?: boolean;
  isFetching?: boolean;
  emptyMessage?: React.ReactNode;
  sort?: string;
  order?: "asc" | "desc";
  onSort?: (key: string) => void;
  onEmail?: (row: PropertiesTableRow) => void;
  showBiddingEdit?: boolean;
  /** Extra classes for the outer card. Use `flex-1 min-h-0` to fill parent. */
  className?: string;
}) {
  void isFetching;

  return (
    <div className={cn("card flex min-h-0 flex-col overflow-hidden", className)}>
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-[var(--surface)]">
            <tr className="border-b border-[var(--border)]">
              {COLUMNS.map((c) => (
                <th
                  key={c.key as string}
                  style={{ minWidth: c.width }}
                  className="px-3 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]"
                >
                  {c.sortable && onSort ? (
                    <button
                      type="button"
                      onClick={() => onSort(c.key as string)}
                      className="inline-flex items-center gap-1 hover:text-[var(--foreground)]"
                    >
                      {c.label}
                      {sort === c.key &&
                        (order === "asc" ? (
                          <ArrowUp className="h-3 w-3" />
                        ) : (
                          <ArrowDown className="h-3 w-3" />
                        ))}
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
                <td
                  colSpan={COLUMNS.length + 1}
                  className="p-10 text-center text-sm text-[var(--muted-foreground)]"
                >
                  {emptyMessage ?? "No properties to show."}
                </td>
              </tr>
            )}
            {items.map((p, idx) => (
              <tr
                key={p.id}
                className={cn(
                  "border-b border-[var(--border)] hover:bg-[var(--muted)]",
                  idx % 2 === 1 && "bg-[var(--surface-2)]",
                )}
              >
                {COLUMNS.map((c) => (
                  <td key={c.key as string} className="px-3 py-2.5">
                    {c.key === "bidding_price" && showBiddingEdit ? (
                      <BiddingCell property={p} />
                    ) : (
                      renderCell(p, c.key)
                    )}
                  </td>
                ))}
                <td className="sticky right-0 bg-[var(--surface)] px-3 py-2.5 text-right">
                  <div className="flex justify-end gap-1">
                    {onEmail && (
                      <button
                        type="button"
                        onClick={() => onEmail(p)}
                        className="rounded-lg p-1.5 text-[var(--color-brand-600)] hover:bg-[var(--color-brand-50)]"
                        title="Send email"
                      >
                        <Mail className="h-4 w-4" />
                      </button>
                    )}
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
    </div>
  );
}

/** Inline editable bidding price cell. PATCHes /properties/{id}. */
function BiddingCell({ property }: { property: PropertiesTableRow }) {
  const qc = useQueryClient();
  const [value, setValue] = useState<string>(property.bidding_price ?? "");
  const [original, setOriginal] = useState<string>(property.bidding_price ?? "");

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
      qc.invalidateQueries({ queryKey: ["dashboard"] });
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

function renderCell(p: PropertiesTableRow, key: keyof PropertiesTableRow) {
  const v = p[key];
  if (v === null || v === undefined || v === "")
    return <span className="text-[var(--muted-foreground)]">—</span>;

  if (key === "email_status") return <StatusChip status={String(v)} />;
  if (key === "scrape_date" || key === "sheet_tab")
    return <span className="text-xs text-[var(--muted-foreground)]">{String(v)}</span>;
  if (key === "address") return <span className="font-medium">{String(v)}</span>;
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

// Re-export — Property is wider than PropertiesTableRow but compatible.
export type { Property };
