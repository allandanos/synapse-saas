"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

interface OrgRead {
  id: string;
  slug: string;
  name: string;
  status: string;
  created_at: string;
}

export default function SettingsPage() {
  const { activeOrgId, entitlements } = useAuth();
  const queryClient = useQueryClient();
  // Unsaved edit, scoped to the org it was typed for: switching orgs discards
  // it, so Save can never PATCH one org with another org's name.
  const [draft, setDraft] = useState<{ orgId: string | null; value: string } | null>(null);

  const { data: org } = useQuery({
    queryKey: ["org", activeOrgId],
    queryFn: () => api<OrgRead>("/v1/orgs/current"),
    enabled: Boolean(activeOrgId),
  });

  const pendingEdit = draft?.orgId === activeOrgId ? draft.value : null;
  const name = pendingEdit ?? org?.name ?? "";

  const save = useMutation({
    mutationFn: () =>
      api("/v1/orgs/current", { method: "PATCH", body: JSON.stringify({ name }) }),
    onSuccess: async () => {
      // Prefix match: also refreshes billing's ["org"] query.
      await queryClient.invalidateQueries({ queryKey: ["org"] });
      setDraft(null);
    },
  });

  if (!activeOrgId) return null;

  return (
    <div>
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <p className="mt-1 text-sm text-zinc-500">Organization profile.</p>
      </header>

      {org && (
        <dl className="mb-8 grid max-w-md grid-cols-[8rem_1fr] gap-y-2 text-sm">
          <dt className="text-zinc-400">Slug</dt>
          <dd className="font-mono">{org.slug}</dd>
          <dt className="text-zinc-400">Status</dt>
          <dd>{org.status}</dd>
          <dt className="text-zinc-400">Created</dt>
          <dd>{new Date(org.created_at).toLocaleDateString()}</dd>
          <dt className="text-zinc-400">Plan</dt>
          <dd>{entitlements?.plan_key ?? "—"}</dd>
        </dl>
      )}

      <form
        key={activeOrgId}
        onSubmit={(e) => {
          e.preventDefault();
          save.mutate();
        }}
        className="max-w-md"
      >
        <label htmlFor="org-name" className="mb-1.5 block text-sm font-medium text-zinc-700">
          Organization name
        </label>
        <div className="flex gap-3">
          <input
            id="org-name"
            required
            minLength={2}
            value={name}
            onChange={(e) => setDraft({ orgId: activeOrgId, value: e.target.value })}
            className="flex-1 rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
          <button
            type="submit"
            disabled={save.isPending || name === org?.name}
            className="rounded-lg bg-primary px-5 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {save.isPending ? "Saving…" : save.isSuccess ? "Saved" : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
}
