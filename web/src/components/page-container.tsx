/**
 * Page container — full viewport height column.
 *
 * Responsive: tight padding on phones (cards reach close to the edges,
 * iOS-style), generous padding on desktop. Extra bottom padding on
 * phones so the fixed bottom tab bar doesn't clip the last row.
 *
 * - Default: vertically scrolls if content overflows.
 * - `fill`: overflow-hidden + flex column for full-height single-pane
 *   pages (dashboard, global data) where one child is flex-1.
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
        "mx-auto flex h-full w-full max-w-[1600px] flex-1 flex-col px-3 pt-3 sm:px-6 md:p-8",
        // Bottom padding accounts for the mobile bottom tab bar
        // (h-14 + safe-area). On md+ the bar is hidden so no extra
        // space needed.
        fill ? "overflow-hidden pb-3 md:pb-0" : "overflow-y-auto pb-20 md:pb-8",
        className,
      )}
    >
      {children}
    </div>
  );
}
