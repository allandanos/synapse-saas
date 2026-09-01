"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";

interface Endpoint {
  id: string;
  url: string;
  events: string[];
  is_active: boolean;
  created_at: string;
}

interface Delivery {
  id: string;
  event_type: string;
  status: string;
  attempts: number;
  last_response_code: number | null;
  created_at: string;
}

export default function WebhooksPage() {
  const queryClient = useQueryClient();
  const [url, setUrl] = useState("");
  const [newSecret, setNewSecret] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: endpoints } = useQuery({
    queryKey: ["webhook-endpoints"],
    queryFn: () => api<Endpoint[]>("/v1/webhooks/endpoints"),
  });
  const { data: deliveries } = useQuery({
    queryKey: ["webhook-deliveries"],
    queryFn: () => api<Delivery[]>("/v1/webhooks/deliveries"),
  });

  const create = useMutation({
    mutationFn: () =>
      api<{ secret: string }>("/v1/webhooks/endpoints", {
        method: "POST",
        body: JSON.stringify({ url, events: [] }),
      }),
    onSuccess: (result) => {
      setUrl("");
      setNewSecret(result.secret);
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["webhook-endpoints"] });
    },
    onError: (err) => setError(err instanceof Error ? err.message : "Failed"),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/v1/webhooks/endpoints/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["webhook-endpoints"] }),
  });

  const retry = useMutation({
    mutationFn: (id: string) => api(`/v1/webhooks/deliveries/${id}/retry`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["webhook-deliveries"] }),
  });

  return (
    <div>
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Webhooks</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Signed <code className="rounded bg-zinc-100 px-1 text-xs">X-Synapse-Signature</code>{" "}
          deliveries with exponential backoff.
        </p>
      </header>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (url.trim()) create.mutate();
        }}
        className="mb-6 flex gap-3"
      >
        <label htmlFor="wh-url" className="sr-only">
          Endpoint URL
        </label>
        <input
          id="wh-url"
          type="url"
          required
          placeholder="https://example.com/hooks/synapse"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className="flex-1 rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-900"
        />
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded-lg bg-zinc-900 px-5 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50"
        >
          Add endpoint
        </button>
      </form>

      {error && (
        <p role="alert" className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}

      {newSecret && (
        <div className="mb-6 rounded-lg border border-amber-200 bg-amber-50 p-4">
          <p className="text-sm font-medium text-amber-900">
            Save this signing secret now — it is shown only once.
          </p>
          <code className="mt-2 block break-all rounded bg-white px-3 py-2 font-mono text-xs text-amber-900">
            {newSecret}
          </code>
          <button onClick={() => setNewSecret(null)} className="mt-2 text-xs text-amber-700 underline">
            I&apos;ve saved it
          </button>
        </div>
      )}

      <section aria-label="Endpoints" className="mb-10 space-y-2">
        {(endpoints ?? []).map((ep) => (
          <div
            key={ep.id}
            className="flex items-center justify-between rounded-lg border border-zinc-200 px-4 py-3"
          >
            <div className="min-w-0">
              <p className="truncate font-mono text-sm text-zinc-700">{ep.url}</p>
              <p className="text-xs text-zinc-400">
                {ep.events.length === 0 ? "all events" : ep.events.join(", ")}
              </p>
            </div>
            <button
              onClick={() => remove.mutate(ep.id)}
              className="text-xs text-zinc-400 underline hover:text-red-600"
            >
              Remove
            </button>
          </div>
        ))}
        {(endpoints ?? []).length === 0 && (
          <p className="rounded-lg border border-dashed border-zinc-300 px-4 py-8 text-center text-sm text-zinc-400">
            No endpoints registered.
          </p>
        )}
      </section>

      <section aria-labelledby="deliveries-h">
        <h2 id="deliveries-h" className="mb-4 text-sm font-semibold uppercase tracking-wide text-zinc-500">
          Recent deliveries
        </h2>
        <div className="overflow-hidden rounded-xl border border-zinc-200">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="px-4 py-3 font-medium">Event</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Attempts</th>
                <th className="px-4 py-3 font-medium sr-only">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {(deliveries ?? []).map((d) => (
                <tr key={d.id}>
                  <td className="px-4 py-3 font-mono text-xs">{d.event_type}</td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        d.status === "delivered"
                          ? "bg-emerald-50 text-emerald-700"
                          : d.status === "exhausted"
                            ? "bg-red-50 text-red-700"
                            : "bg-amber-50 text-amber-700"
                      }`}
                    >
                      {d.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 tabular-nums text-zinc-500">{d.attempts}</td>
                  <td className="px-4 py-3 text-right">
                    {d.status !== "delivered" && (
                      <button
                        onClick={() => retry.mutate(d.id)}
                        className="text-xs text-zinc-400 underline hover:text-zinc-900"
                      >
                        Retry
                      </button>
                    )}
                  </td>
                </tr>
              ))}
              {(deliveries ?? []).length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-zinc-400">
                    No deliveries yet.
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
