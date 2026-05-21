"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Sidebar } from "./sidebar";
import { MobileNav } from "./mobile-nav";
import { MobileTopBar } from "./mobile-topbar";
import { useAuth } from "@/lib/auth";

/**
 * AppShell — responsive layout chrome.
 *
 * Desktop (md+):  classic side rail + full-height content column.
 * Mobile (<md):   sticky frosted top bar, scrollable content, fixed
 *                 frosted bottom tab bar (iOS pattern). Content gets
 *                 padding to clear both chrome layers.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const router = useRouter();
  const { token, loading } = useAuth();

  useEffect(() => {
    if (!loading && !token) router.replace("/login");
  }, [loading, token, router]);

  useEffect(() => {
    const v = window.localStorage.getItem("sidebar_collapsed");
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (v === "1") setCollapsed(true);
  }, []);
  useEffect(() => {
    window.localStorage.setItem("sidebar_collapsed", collapsed ? "1" : "0");
  }, [collapsed]);

  if (loading) {
    return (
      <div className="grid min-h-screen place-items-center">
        <div className="text-sm text-[var(--muted-foreground)]">Loading…</div>
      </div>
    );
  }
  if (!token) return null;

  return (
    <div
      className="flex overflow-hidden bg-[var(--background)]"
      // Constrain to the dynamic viewport so iOS Safari's collapsing
      // address bar doesn't trash our calc(100dvh-…) heights. Inner
      // panes own their scroll behaviour via PageContainer.
      style={{ height: "100dvh" }}
    >
      {/* Side rail — desktop only. */}
      <div className="hidden md:flex">
        <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />
      </div>

      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <MobileTopBar />
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {children}
        </div>
      </main>

      <MobileNav />
    </div>
  );
}
