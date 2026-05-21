/**
 * Page container — adaptive layout column.
 *
 * Two behaviours, controlled by `fill`:
 *
 *   fill=false (default — Dashboard, Scraper, Emails, Profile)
 *     - Page scrolls naturally (document scroll on mobile, container
 *       scroll on desktop).
 *     - Mobile gets extra bottom padding so the fixed tab bar doesn't
 *       clip the last block.
 *
 *   fill=true (Global Data — single full-height pane with a
 *     virtualised table inside)
 *     - Height-constrained on both viewports so the child table can
 *       flex-1 and scroll internally.
 *     - Mobile: 100dvh minus top bar + tab bar + safe area.
 *     - Desktop: h-full (filled by parent flex column).
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
  if (fill) {
    return (
      <div
        className={cn(
          // Mobile: clamp to viewport minus mobile chrome (top bar 3rem
          // + bottom tab bar 3.5rem). md+ ignores and fills its parent.
          "mx-auto flex h-[calc(100dvh-6.5rem)] w-full max-w-[1600px] flex-1 flex-col overflow-hidden px-3 pt-3 sm:px-6 md:h-full md:p-8",
          className,
        )}
      >
        {children}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "mx-auto flex w-full max-w-[1600px] flex-1 flex-col px-3 pt-3 pb-24 sm:px-6 md:h-full md:overflow-y-auto md:p-8",
        className,
      )}
    >
      {children}
    </div>
  );
}
