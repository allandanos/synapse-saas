"use client";

/* Usage meter: used vs limit with soft-limit amber state. */

import { formatMetric } from "@/lib/api";
import type { UsageCheck } from "@/lib/api";

export function UsageMeter({ check }: { check: UsageCheck }) {
  const unlimited = check.limit === null;
  const limit = check.limit ?? 0;
  const pct = unlimited || limit === 0 ? 0 : Math.min(100, (check.used / limit) * 100);
  const hard = !unlimited && check.used >= limit;
  const soft = check.soft_limit_breached && !hard;

  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium text-zinc-700">
          {check.metric.replaceAll("_", " ")}
        </span>
        <span className={`text-sm tabular-nums ${hard ? "font-semibold text-red-600" : "text-zinc-500"}`}>
          {formatMetric(check.metric, check.used)}
          {!unlimited && <span className="text-zinc-400"> / {formatMetric(check.metric, limit)}</span>}
          {unlimited && <span className="text-zinc-400"> / unlimited</span>}
        </span>
      </div>
      <div className="mt-2 h-2 overflow-hidden rounded-full bg-zinc-100" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100} aria-label={check.metric}>
        <div
          className={`h-full rounded-full transition-all ${
            hard ? "bg-red-500" : soft ? "bg-amber-500" : "bg-zinc-900"
          }`}
          style={{ width: `${unlimited ? 4 : Math.max(pct, 2)}%` }}
        />
      </div>
      {hard && (
        <p className="mt-1.5 text-xs text-red-600">
          Limit reached — upgrade to continue this period.
        </p>
      )}
      {soft && !hard && (
        <p className="mt-1.5 text-xs text-amber-600">Approaching the plan limit.</p>
      )}
    </div>
  );
}
