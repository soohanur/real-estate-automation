/**
 * Page container — single layout column inside the AppShell's
 * constrained viewport. AppShell guarantees a fixed-height parent
 * (100dvh — top bar — tab bar accounted for via flex), so we always
 * use h-full + flex column here.
 *
 *   fill=false (default — Dashboard, Scraper, Emails, Profile)
 *     - Container scrolls internally (overflow-y-auto). Mobile-style
 *       smooth scroll inside a chrome-clipped frame.
 *
 *   fill=true (Global Data)
 *     - overflow-hidden so a child component (the virtualised table)
 *       owns the scroll surface and can measure its own height.
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
        "mx-auto flex h-full w-full max-w-[1600px] flex-1 flex-col px-3 py-3 sm:px-6 md:p-8",
        fill ? "overflow-hidden" : "overflow-y-auto",
        // iOS-style overscroll bounce contained to this pane (so the
        // page underneath the table doesn't rubber-band).
        "overscroll-contain",
        className,
      )}
    >
      {children}
    </div>
  );
}
