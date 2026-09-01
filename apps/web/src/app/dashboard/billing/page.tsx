"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check } from "lucide-react";
import { api, formatMoney, type Invoice, type Plan, type Subscription } from "@/lib/api";

export default function BillingPage() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);

  const { data: plans } = useQuery({
    queryKey: ["plans"],
    queryFn: () => api<Plan[]>("/v1/plans"),
  });
  const { data: subscription } = useQuery({
    queryKey: ["subscription"],
    queryFn: () =>
      api<{ subscription: Subscription | null }>("/v1/subscription").then((r) => r.subscription),
  });
  const { data: invoices } = useQuery({
    queryKey: ["invoices"],
    queryFn: () => api<Invoice[]>("/v1/billing/invoices"),
  });

  const changePlan = useMutation({
    mutationFn: async (planKey: string) => {
      // Manual provider: checkout returns instructions; confirm activates.
      const checkout = await api<{ url: string | null; manual_instructions: string | null }>(
        "/v1/billing/checkout",
        { method: "POST", body: JSON.stringify({ plan_key: planKey }) },
      );
      if (checkout.url) {
        window.location.href = checkout.url;
        return "redirecting";
      }
      const confirmed = await api<{ status: string; plan_key: string }>(
        "/v1/billing/checkout/confirm",
        { method: "POST", body: JSON.stringify({ plan_key: planKey }) },
      );
      return `Activated ${confirmed.plan_key} (${confirmed.status})`;
    },
    onSuccess: (result) => {
      if (result !== "redirecting") setMessage(result);
      queryClient.invalidateQueries({ queryKey: ["subscription"] });
      queryClient.invalidateQueries({ queryKey: ["invoices"] });
    },
    onError: (err) => setMessage(err instanceof Error ? err.message : "Plan change failed"),
  });

  const cancel = useMutation({
    mutationFn: () =>
      api("/v1/subscription/cancel", {
        method: "POST",
        body: JSON.stringify({ at_period_end: true }),
      }),
    onSuccess: () => {
      setMessage("Subscription will cancel at period end.");
      queryClient.invalidateQueries({ queryKey: ["subscription"] });
    },
  });

  const currentKey = subscription?.plan_snapshot.key;

  return (
    <div>
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Billing</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Plans come from <code className="rounded bg-zinc-100 px-1 text-xs">config/plans.yaml</code>{" "}
          — pricing is configuration, not code.
        </p>
      </header>

      {message && (
        <p role="status" className="mb-6 rounded-lg bg-zinc-100 px-3 py-2 text-sm text-zinc-800">
          {message}
        </p>
      )}

      <section aria-label="Plans" className="grid gap-4 md:grid-cols-3">
        {(plans ?? []).map((plan) => {
          const isCurrent = plan.key === currentKey;
          return (
            <div
              key={plan.key}
              className={`flex flex-col rounded-xl border p-6 ${
                isCurrent ? "border-zinc-900 ring-1 ring-zinc-900" : "border-zinc-200"
              }`}
            >
              <div className="flex items-baseline justify-between">
                <h2 className="font-semibold">{plan.name}</h2>
                {isCurrent && (
                  <span className="rounded-full bg-zinc-900 px-2 py-0.5 text-xs font-medium text-white">
                    Current
                  </span>
                )}
              </div>
              <p className="mt-2 text-2xl font-semibold tracking-tight">
                {formatMoney(plan.price_cents, plan.currency)}
                {plan.price_cents !== null && (
                  <span className="text-sm font-normal text-zinc-400">/{plan.interval}</span>
                )}
              </p>
              <ul className="mt-4 flex-1 space-y-1.5 text-sm text-zinc-600">
                {plan.features.map((f) => (
                  <li key={f.feature_key} className="flex items-center gap-2">
                    <Check className="h-3.5 w-3.5 text-zinc-400" aria-hidden />
                    {f.feature_key.replaceAll("_", " ")}
                  </li>
                ))}
              </ul>
              <button
                onClick={() => changePlan.mutate(plan.key)}
                disabled={isCurrent || changePlan.isPending}
                className={`mt-6 rounded-lg py-2 text-sm font-medium ${
                  isCurrent
                    ? "cursor-default bg-zinc-100 text-zinc-400"
                    : "bg-zinc-900 text-white hover:bg-zinc-700"
                }`}
              >
                {isCurrent ? "Active" : changePlan.isPending ? "Working…" : "Switch plan"}
              </button>
            </div>
          );
        })}
      </section>

      {subscription && (
        <div className="mt-6">
          <button
            onClick={() => cancel.mutate()}
            disabled={cancel.isPending}
            className="text-sm text-zinc-400 underline hover:text-red-600"
          >
            Cancel at period end
          </button>
        </div>
      )}

      <section aria-labelledby="invoices-h" className="mt-10">
        <h2 id="invoices-h" className="mb-4 text-sm font-semibold uppercase tracking-wide text-zinc-500">
          Invoices
        </h2>
        <div className="overflow-hidden rounded-xl border border-zinc-200">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="px-4 py-3 font-medium">Date</th>
                <th className="px-4 py-3 font-medium">Amount</th>
                <th className="px-4 py-3 font-medium">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {(invoices ?? []).map((inv) => (
                <tr key={inv.id}>
                  <td className="px-4 py-3 text-zinc-600">
                    {new Date(inv.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 font-medium tabular-nums">
                    {formatMoney(inv.total_cents, inv.currency)}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        inv.status === "paid"
                          ? "bg-emerald-50 text-emerald-700"
                          : "bg-amber-50 text-amber-700"
                      }`}
                    >
                      {inv.status}
                    </span>
                  </td>
                </tr>
              ))}
              {(invoices ?? []).length === 0 && (
                <tr>
                  <td colSpan={3} className="px-4 py-8 text-center text-zinc-400">
                    No invoices yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
