"use client";

import Link from "next/link";
import {
  memo,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import {
  ArrowDown,
  ArrowUp,
  Check,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Image as ImageIcon,
  Loader2,
  Mail,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { propertiesApi, type Property } from "@/lib/api/properties";
import { cn } from "@/lib/utils";

/** Funda brand glyph (SVG, no external dep). */
function FundaIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="currentColor"
      className={className}
      aria-hidden="true"
    >
      <path d="M4 21V5a2 2 0 0 1 2-2h6.5a2 2 0 0 1 1.41.59L19.4 9.1a2 2 0 0 1 .6 1.41V21a0 0 0 0 1 0 0H4Zm3-9h6v-2H7v2Zm0 4h10v-2H7v2Z" />
    </svg>
  );
}

export type PropertiesTableRow = {
  id: number;
  url: string;
  scrape_date?: string | null;
  address?: string | null;
  listed_since?: string | null;
  days_on_market?: string | null;
  asking_price?: string | null;
  woz_value?: string | null;
  suggested_bid?: string | null;
  bidding_price?: string | null;
  price_per_m2?: string | null;
  living_area?: string | null;
  plot_area?: string | null;
  rooms?: string | null;
  bedrooms?: string | null;
  construction_year?: string | null;
  property_type?: string | null;
  energy_label?: string | null;
  heating?: string | null;
  insulation?: string | null;
  maintenance_inside?: string | null;
  maintenance_outside?: string | null;
  garden?: string | null;
  garden_orientation?: string | null;
  parking?: string | null;
  vve?: string | null;
  erfpacht?: string | null;
  acceptance?: string | null;
  description?: string | null;
  images?: string | null;
  agency_name?: string | null;
  agency_phone?: string | null;
  agency_email?: string | null;
  agency_website?: string | null;
  sheet_tab?: string | null;
  email_status?: string | null;
};

type ColumnDef = {
  key: keyof PropertiesTableRow;
  label: string;
  sortable?: boolean;
  width: string; // CSS length used for grid-template-columns
};

const COLUMNS: ColumnDef[] = [
  { key: "scrape_date", label: "Scrape Date", sortable: true, width: "130px" },
  { key: "address", label: "Address", sortable: true, width: "240px" },
  { key: "listed_since", label: "Listed Since", sortable: true, width: "110px" },
  { key: "days_on_market", label: "DOM", sortable: true, width: "70px" },
  { key: "asking_price", label: "Asking", sortable: true, width: "110px" },
  { key: "woz_value", label: "WOZ", sortable: true, width: "110px" },
  { key: "suggested_bid", label: "Suggested", sortable: true, width: "110px" },
  { key: "bidding_price", label: "Bidding (edit)", width: "150px" },
  { key: "images", label: "Images", width: "110px" },
  { key: "price_per_m2", label: "€/m²", width: "80px" },
  { key: "living_area", label: "m²", width: "70px" },
  { key: "plot_area", label: "Plot m²", width: "80px" },
  { key: "rooms", label: "Rooms", width: "70px" },
  { key: "bedrooms", label: "Beds", width: "60px" },
  { key: "construction_year", label: "Year", width: "70px" },
  { key: "property_type", label: "Type", sortable: true, width: "180px" },
  { key: "energy_label", label: "Energy", sortable: true, width: "70px" },
  { key: "heating", label: "Heating", width: "140px" },
  { key: "insulation", label: "Insulation", width: "150px" },
  { key: "maintenance_inside", label: "Maint. In", width: "120px" },
  { key: "maintenance_outside", label: "Maint. Out", width: "120px" },
  { key: "garden", label: "Garden", width: "140px" },
  { key: "garden_orientation", label: "Orient.", width: "120px" },
  { key: "parking", label: "Parking", width: "140px" },
  { key: "vve", label: "VVE", width: "100px" },
  { key: "erfpacht", label: "Erfpacht", width: "120px" },
  { key: "acceptance", label: "Acceptance", width: "140px" },
  { key: "description", label: "Description", width: "260px" },
  { key: "agency_name", label: "Agency", sortable: true, width: "160px" },
  { key: "agency_phone", label: "Phone", width: "130px" },
  { key: "agency_email", label: "Email", width: "180px" },
  { key: "agency_website", label: "Website", width: "180px" },
  { key: "sheet_tab", label: "Range", width: "120px" },
  { key: "email_status", label: "Status", sortable: true, width: "110px" },
];

const ROW_HEIGHT = 48; // px — must match the .row min-h utility below
const ACTIONS_WIDTH = "140px";
const GRID_TEMPLATE = COLUMNS.map((c) => c.width).join(" ") + ` ${ACTIONS_WIDTH}`;

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
  className?: string;
}) {
  void isFetching;

  const scrollRef = useRef<HTMLDivElement | null>(null);
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
  });

  // Lightbox + cell modal state lives on the parent so child rows don't
  // need to be re-rendered when the modal opens/closes.
  const [lightbox, setLightbox] = useState<{ images: string[]; address: string } | null>(null);
  const [cellModal, setCellModal] = useState<{ label: string; value: string } | null>(null);

  const openLightbox = useCallback(
    (images: string[], address: string) => setLightbox({ images, address }),
    [],
  );
  const openCellModal = useCallback(
    (label: string, value: string) => setCellModal({ label, value }),
    [],
  );
  const handleEmail = useCallback(
    (row: PropertiesTableRow) => onEmail?.(row),
    [onEmail],
  );

  const totalGridWidth = useMemo(() => {
    // Quick sum so the inner grid carries an explicit min-width that
    // makes horizontal overflow scroll inside the parent container.
    const widths = [...COLUMNS.map((c) => c.width), ACTIONS_WIDTH];
    return widths
      .map((w) => parseInt(w.replace("px", ""), 10) || 0)
      .reduce((a, b) => a + b, 0);
  }, []);

  return (
    <div className={cn("card flex min-h-0 flex-col overflow-hidden", className)}>
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto">
        {/* Header */}
        <div
          className="sticky top-0 z-20 grid border-b border-[var(--border)] bg-[var(--surface)] text-[11px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]"
          style={{ gridTemplateColumns: GRID_TEMPLATE, minWidth: totalGridWidth }}
        >
          {COLUMNS.map((c) => (
            <div key={c.key as string} className="px-3 py-3">
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
            </div>
          ))}
          <div className="sticky right-0 bg-[var(--surface)] px-3 py-3 text-right">
            Actions
          </div>
        </div>

        {/* Body */}
        {items.length === 0 && !isLoading ? (
          <div className="p-10 text-center text-sm text-[var(--muted-foreground)]">
            {emptyMessage ?? "No properties to show."}
          </div>
        ) : (
          <div
            style={{
              height: virtualizer.getTotalSize(),
              minWidth: totalGridWidth,
              position: "relative",
            }}
          >
            {virtualizer.getVirtualItems().map((vi) => {
              const p = items[vi.index];
              return (
                <Row
                  key={p.id}
                  property={p}
                  rowIndex={vi.index}
                  onEmail={onEmail ? handleEmail : undefined}
                  onOpenImages={openLightbox}
                  onOpenCellModal={openCellModal}
                  showBiddingEdit={showBiddingEdit}
                  style={{
                    position: "absolute",
                    top: 0,
                    left: 0,
                    width: "100%",
                    transform: `translateY(${vi.start}px)`,
                    height: ROW_HEIGHT,
                  }}
                />
              );
            })}
          </div>
        )}
      </div>

      {lightbox && (
        <Lightbox
          images={lightbox.images}
          address={lightbox.address}
          onClose={() => setLightbox(null)}
        />
      )}

      {cellModal && (
        <CellModal
          label={cellModal.label}
          value={cellModal.value}
          onClose={() => setCellModal(null)}
        />
      )}
    </div>
  );
}

// ── Row (memoized) ───────────────────────────────────────────────
const Row = memo(function Row({
  property,
  rowIndex,
  onEmail,
  onOpenImages,
  onOpenCellModal,
  showBiddingEdit,
  style,
}: {
  property: PropertiesTableRow;
  rowIndex: number;
  onEmail?: (row: PropertiesTableRow) => void;
  onOpenImages: (images: string[], address: string) => void;
  onOpenCellModal: (label: string, value: string) => void;
  showBiddingEdit: boolean;
  style: React.CSSProperties;
}) {
  return (
    <div
      style={{ ...style, gridTemplateColumns: GRID_TEMPLATE }}
      className={cn(
        "grid border-b border-[var(--border)] hover:bg-[var(--muted)]",
        rowIndex % 2 === 1 && "bg-[var(--surface-2)]",
      )}
    >
      {COLUMNS.map((c) => (
        <div
          key={c.key as string}
          className="flex h-12 max-h-12 items-center overflow-hidden whitespace-nowrap px-3"
        >
          {c.key === "bidding_price" && showBiddingEdit ? (
            <BiddingCell property={property} />
          ) : c.key === "images" ? (
            <ImagesCell
              property={property}
              onOpen={(images) => onOpenImages(images, property.address ?? "Property")}
            />
          ) : (
            <ClickableCell
              label={c.label}
              value={renderCell(property, c.key)}
              rawValue={(property[c.key] ?? "") as string}
              onOverflow={onOpenCellModal}
            />
          )}
        </div>
      ))}
      <div className="sticky right-0 flex h-12 items-center justify-end gap-1 bg-[var(--surface)] px-3">
        <Link
          href={`/data/${property.id}`}
          className="rounded-lg p-1.5 text-[var(--color-brand-700)] hover:bg-[var(--color-brand-50)]"
          title="View property profile"
        >
          <FundaIcon className="h-4 w-4" />
        </Link>
        {onEmail && (
          <button
            type="button"
            onClick={() => onEmail(property)}
            className="rounded-lg p-1.5 text-[var(--color-brand-600)] hover:bg-[var(--color-brand-50)]"
            title="Send email"
          >
            <Mail className="h-4 w-4" />
          </button>
        )}
        {property.url && (
          <a
            href={property.url}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-lg p-1.5 text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            title="Open on funda.nl"
          >
            <ExternalLink className="h-4 w-4" />
          </a>
        )}
      </div>
    </div>
  );
});

// ── Inline editable bidding price ────────────────────────────────
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
    <div className="flex w-full items-center gap-1">
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

// ── Images cell ──────────────────────────────────────────────────
function parseImages(raw?: string | null): string[] {
  if (!raw) return [];
  return raw
    .split(",")
    .map((u) => u.trim())
    .filter((u) => u.length > 0);
}

function ImagesCell({
  property,
  onOpen,
}: {
  property: PropertiesTableRow;
  onOpen: (images: string[]) => void;
}) {
  const images = parseImages(property.images);
  if (images.length === 0) {
    return <span className="text-[var(--muted-foreground)]">—</span>;
  }
  return (
    <button
      type="button"
      onClick={() => onOpen(images)}
      className="group relative flex items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-2 py-1 hover:border-[var(--color-brand-400)]"
      title={`${images.length} image${images.length === 1 ? "" : "s"}`}
    >
      <span className="relative h-8 w-12 shrink-0 overflow-hidden rounded-md bg-[var(--muted)]">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={images[0]}
          alt=""
          className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-110"
          loading="lazy"
        />
      </span>
      <span className="flex items-center gap-1 text-xs">
        <ImageIcon className="h-3.5 w-3.5" />
        {images.length}
      </span>
    </button>
  );
}

// ── Lightbox ─────────────────────────────────────────────────────
function Lightbox({
  images,
  address,
  onClose,
}: {
  images: string[];
  address: string;
  onClose: () => void;
}) {
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowRight") setIdx((i) => (i + 1) % images.length);
      if (e.key === "ArrowLeft") setIdx((i) => (i - 1 + images.length) % images.length);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [images.length, onClose]);

  if (images.length === 0) return null;

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/85 p-4"
      onClick={onClose}
    >
      <div
        className="relative flex max-h-[90vh] w-full max-w-5xl flex-col gap-3"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between text-white">
          <div className="truncate text-sm font-medium">
            {address} · {idx + 1} / {images.length}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-9 w-9 place-items-center rounded-full bg-white/10 hover:bg-white/20"
            aria-label="Close"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="relative flex h-[70vh] items-center justify-center overflow-hidden rounded-2xl bg-black">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={images[idx]}
            alt={`Image ${idx + 1}`}
            className="max-h-full max-w-full object-contain"
          />

          {images.length > 1 && (
            <>
              <button
                type="button"
                onClick={() => setIdx((i) => (i - 1 + images.length) % images.length)}
                className="absolute left-3 top-1/2 grid h-10 w-10 -translate-y-1/2 place-items-center rounded-full bg-white/15 text-white hover:bg-white/30"
                aria-label="Previous image"
              >
                <ChevronLeft className="h-6 w-6" />
              </button>
              <button
                type="button"
                onClick={() => setIdx((i) => (i + 1) % images.length)}
                className="absolute right-3 top-1/2 grid h-10 w-10 -translate-y-1/2 place-items-center rounded-full bg-white/15 text-white hover:bg-white/30"
                aria-label="Next image"
              >
                <ChevronRight className="h-6 w-6" />
              </button>
            </>
          )}
        </div>

        <div className="flex gap-2 overflow-x-auto pb-1">
          {images.map((src, i) => (
            <button
              key={i}
              type="button"
              onClick={() => setIdx(i)}
              className={cn(
                "h-14 w-20 shrink-0 overflow-hidden rounded-md border-2 transition",
                i === idx ? "border-[var(--color-brand-400)]" : "border-transparent opacity-70 hover:opacity-100",
              )}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={src} alt="" className="h-full w-full object-cover" loading="lazy" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Click-to-expand text cell ────────────────────────────────────
function ClickableCell({
  label,
  value,
  rawValue,
  onOverflow,
}: {
  label: string;
  value: React.ReactNode;
  rawValue: string;
  onOverflow: (label: string, value: string) => void;
}) {
  const text = (rawValue ?? "").toString();
  const handler = () => {
    if (text.trim().length === 0) return;
    onOverflow(label, text);
  };
  return (
    <button
      type="button"
      onClick={handler}
      className="flex w-full max-w-full items-center overflow-hidden text-left"
      title={text || undefined}
    >
      <span className="block w-full truncate">{value}</span>
    </button>
  );
}

function CellModal({
  label,
  value,
  onClose,
}: {
  label: string;
  value: string;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="card relative w-full max-w-2xl overflow-hidden p-0"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--border)] px-5 py-3">
          <div className="text-xs font-semibold uppercase tracking-wider text-[var(--muted-foreground)]">
            {label}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="grid h-8 w-8 place-items-center rounded-full text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="max-h-[70vh] overflow-auto whitespace-pre-wrap break-words p-5 text-sm leading-relaxed">
          {value}
        </div>
      </div>
    </div>
  );
}

// ── Cell renderers ───────────────────────────────────────────────
function renderCell(p: PropertiesTableRow, key: keyof PropertiesTableRow) {
  const v = p[key];
  if (v === null || v === undefined || v === "")
    return <span className="text-[var(--muted-foreground)]">—</span>;

  if (key === "email_status") return <StatusChip status={String(v)} />;
  if (key === "scrape_date" || key === "sheet_tab" || key === "listed_since")
    return <span className="text-xs text-[var(--muted-foreground)]">{String(v)}</span>;
  if (key === "address") return <span className="font-medium">{String(v)}</span>;
  if (key === "agency_email") {
    const email = String(v);
    return (
      <span className="truncate text-[var(--color-brand-600)]">{email}</span>
    );
  }
  if (key === "agency_website") {
    const href = String(v);
    return (
      <span className="inline-flex items-center gap-1 truncate text-[var(--color-brand-600)]">
        <span className="truncate">{href.replace(/^https?:\/\//, "")}</span>
      </span>
    );
  }
  if (key === "agency_phone") {
    return <span className="text-[var(--color-brand-600)]">{String(v)}</span>;
  }
  if (key === "description") {
    return (
      <span
        className="truncate text-xs text-[var(--muted-foreground)]"
        title={String(v)}
      >
        {String(v)}
      </span>
    );
  }
  return <span className="truncate">{String(v)}</span>;
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

export type { Property };
