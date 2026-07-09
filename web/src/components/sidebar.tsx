"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  Menu,
  Building2,
  Database,
  Mail,
  Settings,
  LogOut,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/lib/auth";
import { conversationsApi } from "@/lib/api/conversations";

const items = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/scraper", label: "Funda Scraper", icon: Building2 },
  { href: "/data", label: "Global Data", icon: Database },
  { href: "/emails", label: "Emails", icon: Mail },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar({
  collapsed,
  onToggle,
}: {
  collapsed: boolean;
  onToggle: () => void;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const user = useAuth((s) => s.user);
  const logout = useAuth((s) => s.logout);
  const { data: unread } = useQuery({
    queryKey: ["conversations", "unread"],
    queryFn: conversationsApi.unreadCount,
    refetchInterval: 30_000,
  });
  const unreadCount = unread?.unread ?? 0;

  return (
    <aside
      className={cn(
        "sticky top-0 h-screen shrink-0 border-r border-[var(--border)] bg-[var(--surface)] transition-all duration-200",
        collapsed ? "w-16" : "w-64"
      )}
    >
      <div className="flex h-full flex-col">
        {/* Brand + collapse */}
        <div className="flex h-16 items-center justify-between border-b border-[var(--border)] px-3">
          {!collapsed && (
            <Link href="/dashboard" className="flex items-center gap-2">
              <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-[var(--color-brand-500)] to-[var(--color-brand-700)] text-white shadow-sm">
                <span className="text-base font-extrabold tracking-tight">F</span>
              </div>
              <span className="text-base font-semibold leading-none">Funda</span>
            </Link>
          )}
          <button
            type="button"
            onClick={onToggle}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            className="grid h-9 w-9 place-items-center rounded-xl text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
          >
            <Menu className="h-5 w-5" />
          </button>
        </div>

        {/* Nav */}
        <nav className="flex-1 overflow-y-auto px-2 py-4">
          <ul className="space-y-1">
            {items.map((it) => {
              const active = pathname === it.href || pathname.startsWith(it.href + "/");
              const Icon = it.icon;
              return (
                <li key={it.href}>
                  <Link
                    href={it.href}
                    className={cn(
                      "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
                      active
                        ? "bg-[var(--color-brand-50)] text-[var(--color-brand-700)] dark:bg-[var(--color-brand-900)]/30 dark:text-[var(--color-brand-300)]"
                        : "text-[var(--foreground)] hover:bg-[var(--muted)]"
                    )}
                  >
                    <span className="relative shrink-0">
                      <Icon className={cn("h-5 w-5", active && "text-[var(--color-brand-600)]")} />
                      {it.href === "/emails" && unreadCount > 0 && (
                        <span className="absolute -right-1.5 -top-1.5 grid h-4 min-w-4 place-items-center rounded-full bg-[var(--color-brand-600)] px-1 text-[9px] font-bold text-white">
                          {unreadCount > 99 ? "99+" : unreadCount}
                        </span>
                      )}
                    </span>
                    {!collapsed && (
                      <span className="flex flex-1 items-center justify-between">
                        {it.label}
                        {it.href === "/emails" && unreadCount > 0 && (
                          <span className="grid h-5 min-w-5 place-items-center rounded-full bg-[var(--color-brand-600)] px-1.5 text-[10px] font-bold text-white">
                            {unreadCount > 99 ? "99+" : unreadCount}
                          </span>
                        )}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </nav>

        {/* Footer / user */}
        <div className="border-t border-[var(--border)] p-3">
          <div className={cn("flex items-center gap-3", collapsed && "justify-center")}>
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-[var(--color-brand-100)] text-sm font-semibold text-[var(--color-brand-700)]">
              {(user?.email?.[0] ?? "U").toUpperCase()}
            </div>
            {!collapsed && (
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium">{user?.name ?? user?.email ?? "User"}</div>
                <div className="truncate text-xs text-[var(--muted-foreground)]">{user?.email ?? ""}</div>
              </div>
            )}
            {!collapsed && (
              <button
                type="button"
                onClick={() => {
                  logout();
                  router.replace("/login");
                }}
                aria-label="Sign out"
                className="grid h-9 w-9 place-items-center rounded-xl text-[var(--muted-foreground)] hover:bg-[var(--muted)]"
              >
                <LogOut className="h-4 w-4" />
              </button>
            )}
          </div>
        </div>
      </div>
    </aside>
  );
}
