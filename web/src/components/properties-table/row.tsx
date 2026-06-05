/**
 * Memoized row component for the virtualized table. One <Row /> per
 * visible viewport position; React.memo + stable callbacks keep
 * re-render cost flat regardless of dataset size.
 */
import { memo } from "react";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Mail } from "lucide-react";
import { propertiesApi } from "@/lib/api/properties";
import { cn } from "@/lib/utils";
import { COLUMNS, GRID_TEMPLATE } from "./columns";
import { FundaIcon } from "./icons";
import { BiddingCell } from "./cells/bidding";
import { ImagesCell } from "./cells/images";
import { ClickableCell } from "./cells/clickable";
import { CopyableContactCell } from "./cells/copy-contact";
import { WebsiteCell } from "./cells/website";
import { renderCell } from "./cells/render-cell";
import type { PropertiesTableRow } from "./types";

type RowProps = {
  property: PropertiesTableRow;
  rowIndex: number;
  onEmail?: (row: PropertiesTableRow) => void;
  onOpenImages: (images: string[], address: string) => void;
  onOpenCellModal: (label: string, value: string) => void;
  showBiddingEdit: boolean;
  style: React.CSSProperties;
};

export const Row = memo(function Row({
  property,
  rowIndex,
  onEmail,
  onOpenImages,
  onOpenCellModal,
  showBiddingEdit,
  style,
}: RowProps) {
  const qc = useQueryClient();

  // Warm the React Query cache for the detail endpoint on hover so
  // navigating to the property profile feels instant.
  const onPrefetchProfile = () => {
    qc.prefetchQuery({
      queryKey: ["properties", "detail", property.id],
      queryFn: () => propertiesApi.get(property.id),
      staleTime: 30_000,
    });
  };

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
          ) : c.key === "agency_phone" || c.key === "agency_email" ? (
            <CopyableContactCell
              property={property}
              field={c.key}
              label={c.label}
              onOverflow={onOpenCellModal}
            />
          ) : c.key === "agency_website" ? (
            <WebsiteCell property={property} />
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
      <div
        className={cn(
          "sticky right-0 z-[5] flex h-12 items-center justify-end gap-0.5 bg-[var(--surface)] px-2 md:px-3 md:gap-1",
          // Soft shadow on left edge so it visually floats above the
          // horizontally-scrolling content on mobile.
          "shadow-[-8px_0_12px_-8px_rgba(15,23,42,0.18)] md:shadow-none",
          rowIndex % 2 === 1 && "bg-[var(--surface-2)]",
        )}
      >
        <Link
          href={`/data/${property.id}`}
          className="grid h-8 w-8 place-items-center rounded-lg text-[var(--color-brand-700)] hover:bg-[var(--color-brand-50)] md:h-9 md:w-9"
          title="View property profile"
          onMouseEnter={onPrefetchProfile}
          onTouchStart={onPrefetchProfile}
        >
          <FundaIcon className="h-4 w-4" />
        </Link>
        {onEmail && (
          <button
            type="button"
            onClick={() => onEmail(property)}
            className="grid h-8 w-8 place-items-center rounded-lg text-[var(--color-brand-600)] hover:bg-[var(--color-brand-50)] md:h-9 md:w-9"
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
            className="grid h-8 w-8 place-items-center rounded-lg text-[var(--muted-foreground)] hover:bg-[var(--muted)] md:h-9 md:w-9"
            title="Open on funda.nl"
          >
            <ExternalLink className="h-4 w-4" />
          </a>
        )}
      </div>
    </div>
  );
});
