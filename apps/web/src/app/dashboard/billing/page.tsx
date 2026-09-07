"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Download } from "lucide-react";
import {
  api,
  apiDownload,
  formatMoney,
  type Invoice,
  type Org,
  type Plan,
  type Subscription,
} from "@/lib/api";

export default function BillingPage() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);

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
  const { data: org, refetch: refetchOrg } = useQuery({
    queryKey: ["org"],
    queryFn: () => api<Org>("/v1/orgs/current"),
  });

  const savedBillingEmail =
    typeof org?.settings?.billing_email === "string" ? org.settings.billing_email : "";
  const [billingEmail, setBillingEmail] = useState<string | null>(null);
  const emailValue = billingEmail ?? savedBillingEmail;

  const saveBillingEmail = useMutation({
    mutationFn: async (value: string) => {
      const trimmed = value.trim();
      await api("/v1/orgs/current", {
        method: "PATCH",
        body: JSON.stringify({
          settings: { ...org?.settings, billing_email: trimmed || null },
        }),
      });
      return trimmed;
    },
    onSuccess: (trimmed) => {
      setBillingEmail(null);
      setMessage(trimmed ? "Billing contact saved." : "Billing contact cleared.");
      refetchOrg();
    },
    onError: (err) => setMessage(err instanceof Error ? err.message : "Save failed"),
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

  const downloadPdf = async (invoiceId: string) => {
    setDownloadingId(invoiceId);
    try {
      const { blob, filename } = await apiDownload(`/v1/billing/invoices/${invoiceId}/pdf`);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename ?? `invoice-${invoiceId}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "PDF download failed");
    } finally {
      setDownloadingId(null);
    }
  };

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

      <section
        aria-labelledby="billing-contact-h"
        className="mt-10 rounded-xl border border-zinc-200 p-6"
      >
        <h2
          id="billing-contact-h"
          className="text-sm font-semibold uppercase tracking-wide text-zinc-500"
        >
          Billing contact
        </h2>
        <p className="mt-1 text-sm text-zinc-500">
          Invoice emails (with PDF attached) are delivered here on finalize and payment.
        </p>
        <form
          className="mt-4 flex flex-col gap-2 sm:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            saveBillingEmail.mutate(emailValue);
          }}
        >
          <label htmlFor="billing-email" className="sr-only">
            Billing contact email
          </label>
          <input
            id="billing-email"
            type="email"
            value={emailValue}
            onChange={(e) => setBillingEmail(e.target.value)}
            placeholder="accounts@yourcompany.com"
            className="flex-1 rounded-lg border border-zinc-200 px-3 py-2 text-sm text-zinc-900 placeholder:text-zinc-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900"
          />
          <button
            type="submit"
            disabled={
              saveBillingEmail.isPending ||
              emailValue === savedBillingEmail ||
              (emailValue === "" && savedBillingEmail === "")
            }
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-zinc-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 disabled:cursor-default disabled:bg-zinc-100 disabled:text-zinc-400"
          >
            {saveBillingEmail.isPending ? "Saving…" : "Save"}
          </button>
        </form>
      </section>

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
                <th className="px-4 py-3 font-medium sr-only">Actions</th>
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
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => downloadPdf(inv.id)}
                      disabled={downloadingId === inv.id}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 px-2.5 py-1.5 text-xs font-medium text-zinc-600 transition-colors hover:border-zinc-400 hover:text-zinc-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 disabled:opacity-50"
                      aria-label={`Download invoice PDF${inv.paid_at ? " (paid)" : ""}`}
                    >
                      <Download className="h-3.5 w-3.5" aria-hidden />
                      {downloadingId === inv.id ? "Downloading…" : "PDF"}
                    </button>
                  </td>
                </tr>
              ))}
              {(invoices ?? []).length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-zinc-400">
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
