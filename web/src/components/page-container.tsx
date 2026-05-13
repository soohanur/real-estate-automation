/**
 * Page container — full viewport height column.
 *
 * - Default: vertically scrolls if content overflows (scraper, emails, profile).
 * - Pages that own a single full-height pane (dashboard, global data) pass
 *   `fill` so the container becomes overflow-hidden and the page distributes
 *   space via flex children (toolbar shrink-0 + table flex-1 min-h-0).
 *
 * Spec mandate: pages must NOT have a heading/paragraph at top.
 */
import { cn } from "@/lib/utils";

export function PageContainer({
  children,
  className,
  fill = false,
}: {
  children: React.ReactNode;
  className?: string;
  fill?: boolean;
}) {
  return (
    <div
      className={cn(
        "mx-auto flex h-full w-full max-w-[1600px] flex-1 flex-col p-6 md:p-8",
        fill ? "overflow-hidden" : "overflow-y-auto",
        className,
      )}
    >
      {children}
    </div>
  );
}
