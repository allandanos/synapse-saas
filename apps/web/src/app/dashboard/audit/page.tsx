"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

interface AuditEntry {
  id: string;
  event_type: string;
  actor_type: string;
  created_at: string;
  diff: Record<string, unknown> | null;
}

export default function AuditPage() {
  const [filter, setFilter] = useState("");

  const { data } = useQuery({
    queryKey: ["audit", filter],
    queryFn: () =>
      api<{ data: AuditEntry[] }>(
        `/v1/audit?limit=50${filter ? `&event_type=${encodeURIComponent(filter)}` : ""}`,
      ),
  });

  return (
    <div>
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Audit log</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Every mutation writes an immutable audit row in the same transaction.
        </p>
      </header>

      <div className="mb-4">
        <label htmlFor="audit-filter" className="sr-only">
          Filter by event type
        </label>
        <input
          id="audit-filter"
          placeholder="Filter event type, e.g. member."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-72 rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-900"
        />
      </div>

      <ol className="space-y-2" aria-label="Audit entries">
        {(data?.data ?? []).map((entry) => (
          <li
            key={entry.id}
            className="flex items-baseline gap-4 rounded-lg border border-zinc-200 px-4 py-3"
          >
            <span className="w-36 shrink-0 text-xs tabular-nums text-zinc-400">
              {new Date(entry.created_at).toLocaleString()}
            </span>
            <span className="font-mono text-xs text-zinc-700">{entry.event_type}</span>
            <span className="ml-auto text-xs text-zinc-400">{entry.actor_type}</span>
          </li>
        ))}
        {(data?.data ?? []).length === 0 && (
          <li className="rounded-lg border border-dashed border-zinc-300 px-4 py-10 text-center text-sm text-zinc-400">
            No audit entries{filter ? " match the filter" : " yet"}.
          </li>
        )}
      </ol>
    </div>
  );
}
