"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Sidebar } from "./sidebar";
import { useAuth } from "@/lib/auth";

export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const router = useRouter();
  const { token, loading } = useAuth();

  useEffect(() => {
    if (!loading && !token) router.replace("/login");
  }, [loading, token, router]);

  // Persist collapse state. We hydrate from localStorage once on mount —
  // setState-in-effect is the documented React 19 pattern for client-only
  // storage like this, since SSR has no localStorage.
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
    <div className="flex h-screen overflow-hidden bg-[var(--background)]">
      <Sidebar collapsed={collapsed} onToggle={() => setCollapsed((v) => !v)} />
      <main className="flex min-w-0 flex-1 flex-col overflow-hidden">{children}</main>
    </div>
  );
}
