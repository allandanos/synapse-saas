"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, type UsageCheck } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { FeatureGate } from "@/components/feature-gate";
import { JoinedBanner } from "@/components/joined-banner";
import { UsageMeter } from "@/components/usage-meter";

interface SubscriptionResponse {
  subscription: {
    status: string;
    plan_snapshot: { key: string; name: string };
    current_period_end: string;
  } | null;
  entitlements: { plan_key: string | null; features: string[] };
  usage: { metric: string; used: number }[];
}

export default function DashboardPage() {
  const { entitlements, activeOrgId } = useAuth();

  const subscription = useQuery({
    queryKey: ["subscription", activeOrgId],
    queryFn: () => api<SubscriptionResponse>("/v1/subscription"),
  });
  const usage = useQuery({
    queryKey: ["usage-limits", activeOrgId],
    queryFn: () =>
      api<{ period: string; metrics: UsageCheck[] }>("/v1/usage/summary").then(
        (s) => s.metrics,
      ),
  });

  const data = subscription.data;
  const usageLimits = usage.data;
  const queryError = subscription.error ?? usage.error;
  const plan = data?.subscription?.plan_snapshot.name ?? "—";
  const status = data?.subscription?.status ?? "none";

  return (
    <div>
      <JoinedBanner />
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Plan <span className="font-medium text-zinc-900">{plan}</span> ·{" "}
          <span className={status === "active" ? "text-emerald-600" : "text-amber-600"}>
            {status}
          </span>
          {entitlements && (
            <> · {entitlements.features.length} features enabled</>
          )}
        </p>
      </header>

      {queryError && (
        <p role="alert" className="mb-6 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          Could not load this organization&apos;s data: {queryError.message}
        </p>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-zinc-200 p-6" aria-labelledby="usage-h">
          <h2 id="usage-h" className="mb-4 text-sm font-semibold uppercase tracking-wide text-zinc-500">
            Usage this period
          </h2>
          {usageLimits && usageLimits.length > 0 ? (
            <div className="space-y-5">
              {usageLimits.map((check) => (
                <UsageMeter key={check.metric} check={check} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-zinc-400">
              No usage recorded yet. Meters appear as the org consumes resources.
            </p>
          )}
        </section>

        <section aria-labelledby="entl-h">
          <div className="rounded-xl border border-zinc-200 p-6">
            <h2 id="entl-h" className="mb-4 text-sm font-semibold uppercase tracking-wide text-zinc-500">
              Enabled features
            </h2>
            <ul className="flex flex-wrap gap-2">
              {(entitlements?.features ?? []).map((f) => (
                <li
                  key={f}
                  className="rounded-full bg-zinc-100 px-3 py-1 font-mono text-xs text-zinc-700"
                >
                  {f}
                </li>
              ))}
            </ul>
            <p className="mt-4 text-sm text-zinc-400">
              Gates resolve plan features plus any active grants — never{" "}
              <code className="text-xs">plan == &quot;pro&quot;</code>.
            </p>
          </div>

          <div className="mt-6">
            <FeatureGate feature="advanced_reports">
              <div className="rounded-xl border border-zinc-900 bg-zinc-950 p-6 text-white">
                <h3 className="text-sm font-semibold">Advanced reports</h3>
                <p className="mt-1 text-sm text-zinc-400">
                  You&apos;re entitled to advanced reporting. Your domain app renders
                  whatever it wants here.
                </p>
              </div>
            </FeatureGate>
          </div>
        </section>
      </div>

      <p className="mt-8 text-sm text-zinc-400">
        Manage the subscription in{" "}
        <Link href="/dashboard/billing" className="underline">
          Billing
        </Link>
        .
      </p>
    </div>
  );
}
