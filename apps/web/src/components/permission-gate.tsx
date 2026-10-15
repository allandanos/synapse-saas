"use client";

/* PermissionGate: render children only when the viewer holds `permission` in
 * the active org, else a "no access" panel — the deep-link face of the hidden
 * nav items. Not an alert: a missing permission is a designed state, not an error. */

import Link from "next/link";
import { Lock } from "lucide-react";
import { useAuth } from "@/lib/auth-context";

interface PermissionGateProps {
  /** Undefined = ungated (any member of the org). */
  permission?: string;
  children: React.ReactNode;
}

export function PermissionGate({ permission, children }: PermissionGateProps) {
  const { me, activeOrgId, can } = useAuth();
  if (permission === undefined || can(permission)) return <>{children}</>;

  const orgName = me?.orgs.find((o) => o.id === activeOrgId)?.name ?? "this organization";

  return (
    <section
      aria-labelledby="no-access-h"
      className="rounded-xl border border-dashed border-zinc-300 bg-zinc-50 p-8 text-center"
    >
      <Lock className="mx-auto mb-3 h-6 w-6 text-zinc-400" aria-hidden />
      <h1 id="no-access-h" className="text-lg font-semibold tracking-tight text-zinc-900">
        You don&apos;t have access to this page
      </h1>
      <p className="mt-1 text-sm text-zinc-500">
        Ask an owner or admin of {orgName} to grant the{" "}
        <code className="rounded bg-white px-1.5 py-0.5 text-xs">{permission}</code> permission.
      </p>
      <Link
        href="/dashboard"
        className="mt-4 inline-flex items-center rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90"
      >
        Back to dashboard
      </Link>
    </section>
  );
}
