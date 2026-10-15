"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { TourAutoStart, TourProvider } from "@/components/tour";
import { useAuth } from "@/lib/auth-context";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { me, activeOrgId, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !me) router.replace("/login");
    if (!loading && me && me.orgs.length === 0) router.replace("/onboarding");
  }, [me, loading, router]);

  // Children only mount with an org selected: org-scoped queries never fire
  // without X-Org-Id. Until then (or while a redirect runs) show a placeholder.
  const ready = me !== null && me.orgs.length > 0 && activeOrgId !== null;
  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-50">
        <p className="text-sm text-zinc-400">Loading…</p>
      </div>
    );
  }

  return (
    <TourProvider>
      <TourAutoStart />
      <AppShell>{children}</AppShell>
    </TourProvider>
  );
}
