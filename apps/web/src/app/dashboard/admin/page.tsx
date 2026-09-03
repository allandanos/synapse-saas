"use client";

/* Platform-admin console: org lookup + suspend, feature flags, entitlement
   grants. Shown only to platform admins; the nav entry is filtered too. */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

interface Flag {
  id: string;
  key: string;
  name: string;
  enabled: boolean;
  rollout_percentage: number | null;
}

export default function AdminPage() {
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const [orgQuery, setOrgQuery] = useState("");
  const [grantOrg, setGrantOrg] = useState("");
  const [grantFeature, setGrantFeature] = useState("");
  const [grantDays, setGrantDays] = useState("14");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isPlatformAdmin = me?.is_platform_admin ?? false;

  const { data: flags } = useQuery({
    queryKey: ["admin-flags"],
    queryFn: () => api<Flag[]>("/v1/feature-flags"),
    enabled: isPlatformAdmin,
  });

  const toggleFlag = useMutation({
    mutationFn: (flag: Flag) =>
      api(`/v1/feature-flags/${flag.key}`, {
        method: "PATCH",
        body: JSON.stringify({ enabled: !flag.enabled }),
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-flags"] }),
  });

  const suspendOrg = useMutation({
    mutationFn: (orgId: string) =>
      api(`/v1/orgs/${orgId}/suspend`, { method: "POST" }),
    onSuccess: (_d, orgId) => {
      setMessage(`Org ${orgId.slice(0, 8)}… suspended`);
      setError(null);
    },
    onError: (err) => {
      setError(err instanceof Error ? err.message : "Suspend failed");
      setMessage(null);
    },
  });

  const unsuspendOrg = useMutation({
    mutationFn: (orgId: string) =>
      api(`/v1/orgs/${orgId}/suspend`, { method: "DELETE" }),
    onSuccess: (_d, orgId) => {
      setMessage(`Org ${orgId.slice(0, 8)}… reactivated`);
      setError(null);
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Failed"),
  });

  const grantEntitlement = useMutation({
    mutationFn: () =>
      api("/v1/entitlements/grants", {
        method: "POST",
        body: JSON.stringify({
          feature_key: grantFeature,
          source: "promo",
          duration_days: parseInt(grantDays, 10) || undefined,
        }),
        // grants go through the org-scoped route; org context is the header
      }),
    onSuccess: () => {
      setMessage(`Granted ${grantFeature} for ${grantDays} days`);
      setError(null);
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Grant failed"),
  });

  if (!isPlatformAdmin) {
    return (
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Admin</h1>
        <p className="mt-4 text-sm text-zinc-500">
          Platform administration requires elevated access.
        </p>
      </div>
    );
  }

  return (
    <div>
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Platform admin</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Org lifecycle, feature flags, and entitlement grants across the platform.
        </p>
      </header>

      {message && (
        <p role="status" className="mb-6 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {message}
        </p>
      )}
      {error && (
        <p role="alert" className="mb-6 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {/* ── Org lifecycle ─────────────────────────────────────────────────── */}
      <section aria-labelledby="orgs-h" className="mb-10">
        <h2 id="orgs-h" className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
          Organizations
        </h2>
        <div className="flex flex-wrap gap-3">
          <input
            aria-label="Organization UUID"
            placeholder="Organization UUID"
            value={orgQuery}
            onChange={(e) => setOrgQuery(e.target.value)}
            className="w-72 rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-900"
          />
          <button
            onClick={() => orgQuery.trim() && suspendOrg.mutate(orgQuery.trim())}
            disabled={!orgQuery.trim() || suspendOrg.isPending}
            className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
          >
            Suspend
          </button>
          <button
            onClick={() => orgQuery.trim() && unsuspendOrg.mutate(orgQuery.trim())}
            disabled={!orgQuery.trim() || unsuspendOrg.isPending}
            className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50"
          >
            Reactivate
          </button>
        </div>
        <p className="mt-2 text-xs text-zinc-400">
          Suspended orgs: all member requests are rejected until reactivated.
        </p>
      </section>

      {/* ── Entitlement grants ────────────────────────────────────────────── */}
      <section aria-labelledby="grants-h" className="mb-10">
        <h2 id="grants-h" className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
          Entitlement grant (active org)
        </h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (grantFeature.trim()) grantEntitlement.mutate();
          }}
          className="flex flex-wrap gap-3"
        >
          <input
            aria-label="Feature key"
            placeholder="feature key, e.g. advanced_reports"
            value={grantFeature}
            onChange={(e) => setGrantFeature(e.target.value)}
            className="w-64 rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-900"
          />
          <input
            aria-label="Days"
            type="number"
            min={1}
            placeholder="days"
            value={grantDays}
            onChange={(e) => setGrantDays(e.target.value)}
            className="w-24 rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-900"
          />
          <button
            type="submit"
            disabled={grantEntitlement.isPending}
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50"
          >
            {grantEntitlement.isPending ? "Granting…" : "Grant (promo)"}
          </button>
        </form>
        <p className="mt-2 text-xs text-zinc-400">
          Grants apply to your <span className="font-medium">currently active org</span> — switch
          orgs in the sidebar first. Time-boxed promotions without plan changes.
        </p>
      </section>

      {/* ── Feature flags ─────────────────────────────────────────────────── */}
      <section aria-labelledby="flags-h">
        <h2 id="flags-h" className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">
          Feature flags (global)
        </h2>
        <div className="overflow-hidden rounded-xl border border-zinc-200">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="px-4 py-3 font-medium">Flag</th>
                <th className="px-4 py-3 font-medium">Rollout</th>
                <th className="px-4 py-3 font-medium">State</th>
                <th className="px-4 py-3 font-medium sr-only">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {(flags ?? []).map((flag) => (
                <tr key={flag.id}>
                  <td className="px-4 py-3">
                    <p className="font-mono text-xs">{flag.key}</p>
                    <p className="text-xs text-zinc-400">{flag.name}</p>
                  </td>
                  <td className="px-4 py-3 text-zinc-500">
                    {flag.rollout_percentage !== null ? `${flag.rollout_percentage}%` : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        flag.enabled ? "bg-emerald-50 text-emerald-700" : "bg-zinc-100 text-zinc-500"
                      }`}
                    >
                      {flag.enabled ? "on" : "off"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => toggleFlag.mutate(flag)}
                      disabled={toggleFlag.isPending}
                      className="text-xs text-zinc-400 underline hover:text-zinc-900"
                    >
                      {flag.enabled ? "Turn off" : "Turn on"}
                    </button>
                  </td>
                </tr>
              ))}
              {(flags ?? []).length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-zinc-400">
                    No flags defined.
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
