"use client";

/**
 * PropertiesTable — virtualized data table shared by Global Data and
 * the Dashboard's Latest Scrapes panel. Designed for 100k+ rows by
 * combining:
 *
 *   - CSS grid layout (consistent column widths header ↔ body)
 *   - @tanstack/react-virtual (only ~30 rows in the DOM at a time)
 *   - React.memo + stable handlers (rows skip re-renders on parent state)
 *   - Optional infinite-scroll callback (paginated fetch on scroll)
 *
 * The column set, row component, and individual cell variants live in
 * sibling files for readability.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

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
  showBiddingEdit?: boolean;
  /** Outer card classes. Pass `flex-1` to fill a flex parent. */
  className?: string;
  /** Infinite scroll: called when the user scrolls within ~10 rows of
   * the loaded end. Caller fetches the next page if available. */
  onLoadMore?: () => void;
  hasMore?: boolean;
  isLoadingMore?: boolean;
};

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
  onLoadMore,
  hasMore,
  isLoadingMore,
}: PropertiesTableProps) {
  void isFetching;

  const scrollRef = useRef<HTMLDivElement | null>(null);
  // eslint-disable-next-line react-hooks/incompatible-library
  const virtualizer = useVirtualizer({
    count: items.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
  });

  // Trigger fetch when user scrolls near the end of the loaded set.
  const virtualItems = virtualizer.getVirtualItems();
  useEffect(() => {
    if (!onLoadMore || !hasMore || isLoadingMore) return;
    const last = virtualItems[virtualItems.length - 1];
    if (!last) return;
    if (last.index >= items.length - 10) {
      onLoadMore();
    }
  }, [virtualItems, hasMore, isLoadingMore, items.length, onLoadMore]);

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
    (row: PropertiesTableRow) => onEmail?.(row),
    [onEmail],
  );

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      {/* Single table on every breakpoint. Phones get horizontal
          scroll on the same grid — keeps the inline bidding edit
          available everywhere instead of dropping to a card list. */}
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
      <div className="bg-[var(--surface)] px-3 py-3 text-right md:sticky md:right-0">
        Actions
      </div>
    </div>
  );
}

export type { PropertiesTableRow, Property };
