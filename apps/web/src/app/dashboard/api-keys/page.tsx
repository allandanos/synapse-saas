"use client";

/* API keys management: create (secret shown once), list, revoke. */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  expires_at: string | null;
  last_used_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export default function ApiKeysPage() {
  const { entitlements } = useAuth();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [newKey, setNewKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // api_access gates programmatic API usage — surface it when missing
  const hasApiAccess = entitlements?.features.includes("api_access") ?? false;

  const { data: keys } = useQuery({
    queryKey: ["api-keys"],
    queryFn: () => api<ApiKey[]>("/v1/api-keys"),
  });

  const create = useMutation({
    mutationFn: () => api<{ key: string }>("/v1/api-keys", {
      method: "POST",
      body: JSON.stringify({ name: name || "unnamed key", scopes: [] }),
    }),
    onSuccess: (result) => {
      setName("");
      setNewKey(result.key);
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["api-keys"] });
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Failed to create key"),
  });

  const revoke = useMutation({
    mutationFn: (id: string) => api(`/v1/api-keys/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["api-keys"] }),
  });

  return (
    <div>
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">API keys</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Programmatic access to this organization&apos;s resources. Authenticate with{" "}
          <code className="rounded bg-zinc-100 px-1 text-xs">Authorization: Bearer sk_…</code>
        </p>
      </header>

      {!hasApiAccess && (
        <p className="mb-6 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          The current plan does not include <code>api_access</code> — upgrade to use the API.
        </p>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) create.mutate();
        }}
        className="mb-6 flex gap-3"
      >
        <label htmlFor="key-name" className="sr-only">
          New key name
        </label>
        <input
          id="key-name"
          required
          placeholder="e.g. CI pipeline"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="flex-1 rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-900"
        />
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded-lg bg-zinc-900 px-5 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50"
        >
          {create.isPending ? "Creating…" : "Create key"}
        </button>
      </form>

      {error && (
        <p role="alert" className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {newKey && (
        <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm font-medium text-amber-900">
            Copy this key now — it is shown only once.
          </p>
          <code className="mt-2 block break-all rounded bg-white px-3 py-2 font-mono text-xs text-amber-900">
            {newKey}
          </code>
          <button onClick={() => setNewKey(null)} className="mt-2 text-xs text-amber-700 underline">
            I&apos;ve saved it
          </button>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-zinc-200">
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500">
            <tr>
              <th className="px-4 py-3 font-medium">Key</th>
              <th className="px-4 py-3 font-medium">Last used</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium sr-only">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {(keys ?? []).map((k) => {
              const revoked = k.revoked_at !== null;
              const expired = k.expires_at !== null && new Date(k.expires_at) < new Date();
              return (
                <tr key={k.id} className={revoked ? "opacity-50" : ""}>
                  <td className="px-4 py-3">
                    <p className="font-medium text-zinc-900">{k.name}</p>
                    <p className="font-mono text-xs text-zinc-400">{k.prefix}…</p>
                  </td>
                  <td className="px-4 py-3 text-zinc-500">
                    {k.last_used_at
                      ? new Date(k.last_used_at).toLocaleString()
                      : "never"}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        revoked || expired
                          ? "bg-zinc-100 text-zinc-500"
                          : "bg-emerald-50 text-emerald-700"
                      }`}
                    >
                      {revoked ? "revoked" : expired ? "expired" : "active"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    {!revoked && (
                      <button
                        onClick={() => revoke.mutate(k.id)}
                        className="text-xs text-zinc-400 underline hover:text-red-600"
                      >
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
            {(keys ?? []).length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-zinc-400">
                  No API keys yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
