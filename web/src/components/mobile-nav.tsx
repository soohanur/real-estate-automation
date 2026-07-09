"use client";

/**
 * MobileNav — bottom tab bar shown on phones (< md breakpoint).
 *
 * Liquid-glass treatment: translucent surface, large blur, soft inner
 * highlight. Tap targets are 56px high (44pt min per Apple HIG with a
 * generous overshoot). Active tab is pill-highlighted in brand colour.
 */
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  Building2,
  Database,
  Mail,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { conversationsApi } from "@/lib/api/conversations";

const TABS = [
  { href: "/dashboard", label: "Home",    icon: LayoutDashboard },
  { href: "/scraper",   label: "Scraper", icon: Building2 },
  { href: "/data",      label: "Data",    icon: Database },
  { href: "/emails",    label: "Emails",  icon: Mail },
  { href: "/settings",  label: "Settings", icon: Settings },
];

export function MobileNav() {
  const pathname = usePathname();
  const { data: unread } = useQuery({
    queryKey: ["conversations", "unread"],
    queryFn: conversationsApi.unreadCount,
    refetchInterval: 30_000,
  });
  const unreadCount = unread?.unread ?? 0;
  return (
    <nav
      aria-label="Primary"
      className="glass fixed inset-x-0 bottom-0 z-40 border-t md:hidden pb-safe"
    >
      <ul className="mx-auto flex max-w-[640px] items-stretch justify-around">
        {TABS.map((t) => {
          const active = pathname === t.href || pathname.startsWith(`${t.href}/`);
          const Icon = t.icon;
          return (
            <li key={t.href} className="flex flex-1 justify-center">
              <Link
                href={t.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex h-14 w-full flex-col items-center justify-center gap-0.5 text-[11px] font-medium",
                  "transition-colors",
                  active
                    ? "text-[var(--color-brand-600)]"
                    : "text-[var(--muted-foreground)]",
                )}
              >
                <span
                  className={cn(
                    "relative grid h-9 w-12 place-items-center rounded-2xl",
                    active && "bg-[var(--color-brand-50)]",
                  )}
                >
                  <Icon className="h-5 w-5" />
                  {t.href === "/emails" && unreadCount > 0 && (
                    <span className="absolute right-1.5 top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-[var(--color-brand-600)] px-1 text-[9px] font-bold text-white">
                      {unreadCount > 99 ? "99+" : unreadCount}
                    </span>
                  )}
                </span>
                <span>{t.label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
