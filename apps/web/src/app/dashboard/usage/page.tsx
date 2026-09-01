"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type UsageCheck } from "@/lib/api";
import { UsageMeter } from "@/components/usage-meter";

export default function UsagePage() {
  const { data, isLoading } = useQuery({
    queryKey: ["usage-summary"],
    queryFn: () => api<{ period: string; metrics: UsageCheck[] }>("/v1/usage/summary"),
  });

  return (
    <div>
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Usage</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Period starting {data?.period ?? "…"}. Amber = soft limit reached; red = hard limit.
        </p>
      </header>

      {isLoading ? (
        <p className="text-sm text-zinc-400">Loading meters…</p>
      ) : data && data.metrics.length > 0 ? (
        <div className="max-w-xl space-y-6 rounded-xl border border-zinc-200 p-6">
          {data.metrics.map((check) => (
            <UsageMeter key={check.metric} check={check} />
          ))}
        </div>
      ) : (
        <div className="max-w-xl rounded-xl border border-dashed border-zinc-300 p-10 text-center">
          <p className="text-sm text-zinc-400">
            No usage metered yet. The framework records events via{" "}
            <code className="rounded bg-zinc-100 px-1 text-xs">POST /v1/usage/events</code>.
          </p>
        </div>
      )}
    </div>
  );
}
