"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AppShell } from "@/components/app-shell";
import { PermissionGate } from "@/components/permission-gate";
import { TourAutoStart, TourProvider } from "@/components/tour";
import { useAuth } from "@/lib/auth-context";
import { requiredPermission } from "@/lib/permissions";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { me, activeOrgId, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

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
      <AppShell>
        {/* One guard for every route: a gated page's queries never mount for a
         * viewer who lacks the permission. */}
        <PermissionGate permission={requiredPermission(pathname)}>{children}</PermissionGate>
      </AppShell>
    </TourProvider>
  );
}
