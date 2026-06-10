"use client";

/**
 * PropertiesTable — responsive data table.
 *
 *   Desktop (md+): virtualised via @tanstack/react-virtual, internal
 *     scroll surface, sticky header + sticky right action column.
 *     Built for 100k+ rows with constant DOM cost.
 *
 *   Mobile (<md):  no internal scroll, no virtualiser. The whole card
 *     grows naturally and the page (PageContainer overflow-y-auto)
 *     owns the scroll surface, matching Dashboard / Scraper / Emails
 *     UX. Infinite scroll still loads 30 rows per page so DOM is
 *     bounded by what the user actually scrolls into view.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useMediaQuery } from "@/lib/use-media-query";

import { COLUMNS, GRID_TEMPLATE, ROW_HEIGHT, TOTAL_GRID_WIDTH } from "./columns";
import { Row } from "./row";
import { Lightbox } from "./lightbox";
import { CellModal } from "./cell-modal";
import type { PropertiesTableRow, Property } from "./types";

type PropertiesTableProps = {
  items: PropertiesTableRow[];
  isLoading?: boolean;
  isFetching?: boolean;
  emptyMessage?: React.ReactNode;
  sort?: string;
  order?: "asc" | "desc";
  onSort?: (key: string) => void;
  onEmail?: (row: PropertiesTableRow) => void;
  onDelete?: (row: PropertiesTableRow) => void;
  showBiddingEdit?: boolean;
  /** Outer card classes. */
  className?: string;
  onLoadMore?: () => void;
  hasMore?: boolean;
  isLoadingMore?: boolean;
};

export function PropertiesTable(props: PropertiesTableProps) {
  // Lightbox + cell-modal state at the parent so memoized rows aren't
  // forced to re-render when modals open / close.
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
    (row: PropertiesTableRow) => props.onEmail?.(row),
    [props],
  );

  const isDesktop = useMediaQuery("(min-width: 768px)");

  return (
    <div className={cn("flex flex-col", isDesktop && "min-h-0", props.className)}>
      {isDesktop ? (
        <DesktopTable
          {...props}
          onOpenImages={openLightbox}
          onOpenCellModal={openCellModal}
          handleEmail={handleEmail}
        />
      ) : (
        <MobileTable
          {...props}
          onOpenImages={openLightbox}
          onOpenCellModal={openCellModal}
          handleEmail={handleEmail}
        />
      )}

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

// ── Desktop: virtualised, internal scroll ─────────────────────────
function DesktopTable({
  items,
  isLoading,
  emptyMessage,
  sort,
  order,
  onSort,
  onEmail,
  onDelete,
  showBiddingEdit = true,
  onLoadMore,
  hasMore,
  isLoadingMore,
  onOpenImages,
  onOpenCellModal,
  handleEmail,
}: PropertiesTableProps & {
  onOpenImages: (images: string[], address: string) => void;
  onOpenCellModal: (label: string, value: string) => void;
  handleEmail: (row: PropertiesTableRow) => void;
}) {
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
  });

  const virtualItems = virtualizer.getVirtualItems();
  useEffect(() => {
    if (!onLoadMore || !hasMore || isLoadingMore) return;
    const last = virtualItems[virtualItems.length - 1];
    if (!last) return;
    if (last.index >= items.length - 10) onLoadMore();
  }, [virtualItems, hasMore, isLoadingMore, items.length, onLoadMore]);

  return (
    <div className="card flex min-h-0 flex-col overflow-hidden">
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto">
        <Header sort={sort} order={order} onSort={onSort} />

        {items.length === 0 && !isLoading ? (
          <div className="p-10 text-center text-sm text-[var(--muted-foreground)]">
            {emptyMessage ?? "No properties to show."}
          </div>
        ) : (
          <div
            style={{
              height: virtualizer.getTotalSize(),
              minWidth: TOTAL_GRID_WIDTH,
              position: "relative",
            }}
          >
            {virtualItems.map((vi) => {
              const p = items[vi.index];
              return (
                <Row
                  key={p.id}
                  property={p}
                  rowIndex={vi.index}
                  onEmail={onEmail ? handleEmail : undefined}
                  onDelete={onDelete}
                  onOpenImages={onOpenImages}
                  onOpenCellModal={onOpenCellModal}
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

        {(isLoadingMore || (!hasMore && items.length > 0)) && (
          <div
            className="flex items-center justify-center gap-2 border-t border-[var(--border)] bg-[var(--surface)] py-3 text-xs text-[var(--muted-foreground)]"
            style={{ minWidth: TOTAL_GRID_WIDTH }}
          >
            {isLoadingMore ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Loading next 30…
              </>
            ) : (
              <span>End of results</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Mobile: no virtualiser, no internal scroll, plain map ─────────
// IntersectionObserver on the sentinel triggers infinite load when
// user scrolls toward the bottom of the page.
function MobileTable({
  items,
  isLoading,
  emptyMessage,
  sort,
  order,
  onSort,
  onEmail,
  onDelete,
  showBiddingEdit = true,
  onLoadMore,
  hasMore,
  isLoadingMore,
  onOpenImages,
  onOpenCellModal,
  handleEmail,
}: PropertiesTableProps & {
  onOpenImages: (images: string[], address: string) => void;
  onOpenCellModal: (label: string, value: string) => void;
  handleEmail: (row: PropertiesTableRow) => void;
}) {
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!onLoadMore || !hasMore) return;
    const el = sentinelRef.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting && !isLoadingMore) {
            onLoadMore();
            break;
          }
        }
      },
      { rootMargin: "400px 0px" },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [onLoadMore, hasMore, isLoadingMore]);

  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <Header sort={sort} order={order} onSort={onSort} />

        {items.length === 0 && !isLoading ? (
          <div className="p-10 text-center text-sm text-[var(--muted-foreground)]">
            {emptyMessage ?? "No properties to show."}
          </div>
        ) : (
          <div style={{ minWidth: TOTAL_GRID_WIDTH }}>
            {items.map((p, idx) => (
              <Row
                key={p.id}
                property={p}
                rowIndex={idx}
                onEmail={onEmail ? handleEmail : undefined}
                onDelete={onDelete}
                onOpenImages={onOpenImages}
                onOpenCellModal={onOpenCellModal}
                showBiddingEdit={showBiddingEdit}
                style={{ height: ROW_HEIGHT }}
              />
            ))}
            <div ref={sentinelRef} style={{ minWidth: TOTAL_GRID_WIDTH, height: 1 }} />
          </div>
        )}

        {(isLoadingMore || (!hasMore && items.length > 0)) && (
          <div
            className="flex items-center justify-center gap-2 border-t border-[var(--border)] bg-[var(--surface)] py-3 text-xs text-[var(--muted-foreground)]"
            style={{ minWidth: TOTAL_GRID_WIDTH }}
          >
            {isLoadingMore ? (
              <>
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Loading next 30…
              </>
            ) : (
              <span>End of results</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Header({
  sort,
  order,
  onSort,
}: {
  sort?: string;
  order?: "asc" | "desc";
  onSort?: (key: string) => void;
}) {
  return (
    <div
      className="sticky top-0 z-20 grid border-b border-[var(--border)] bg-[var(--surface)] text-[11px] font-semibold uppercase tracking-wider text-[var(--muted-foreground)]"
      style={{ gridTemplateColumns: GRID_TEMPLATE, minWidth: TOTAL_GRID_WIDTH }}
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
      <div className="sticky right-0 z-[5] bg-[var(--surface)] px-2 py-3 text-right shadow-[-8px_0_12px_-8px_rgba(15,23,42,0.18)] md:shadow-none md:px-3">
        Actions
      </div>
    </div>
  );
}

export type { PropertiesTableRow, Property };
