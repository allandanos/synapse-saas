"use client";

/* FeatureGate: render children only when the org is entitled, else the
 * upgrade CTA — the frontend face of pricing-as-config. */

import Link from "next/link";
import { Lock } from "lucide-react";
import { useAuth } from "@/lib/auth-context";

export function FeatureGate({
  feature,
  children,
}: {
  feature: string;
  children: React.ReactNode;
}) {
  const { hasFeature } = useAuth();
  if (hasFeature(feature)) return <>{children}</>;

  return (
    <div className="rounded-xl border border-dashed border-zinc-300 bg-zinc-50 p-8 text-center">
      <Lock className="mx-auto mb-3 h-6 w-6 text-zinc-400" aria-hidden />
      <p className="text-sm font-medium text-zinc-900">
        This feature is not on your current plan
      </p>
      <p className="mt-1 text-sm text-zinc-500">
        <code className="rounded bg-white px-1.5 py-0.5 text-xs">{feature}</code> is
        available on higher plans.
      </p>
      <Link
        href="/dashboard/billing"
        className="mt-4 inline-flex items-center rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700"
      >
        View plans
      </Link>
    </div>
  );
}
