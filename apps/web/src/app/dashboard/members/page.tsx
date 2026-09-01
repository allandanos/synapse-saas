"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Member } from "@/lib/api";

export default function MembersPage() {
  const queryClient = useQueryClient();
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);

  const { data: page } = useQuery({
    queryKey: ["members"],
    queryFn: () => api<{ data: Member[]; meta: { total: number } }>("/v1/orgs/current/members"),
  });

  const invite = useMutation({
    mutationFn: (inviteEmail: string) =>
      api("/v1/orgs/current/members/invite", {
        method: "POST",
        body: JSON.stringify({ email: inviteEmail, role_keys: ["member"] }),
      }),
    onSuccess: () => {
      setEmail("");
      setError(null);
      queryClient.invalidateQueries({ queryKey: ["members"] });
    },
    onError: (err) => {
      setError(
        err instanceof ApiError
          ? (err.body.detail as string) ?? "Invite failed"
          : "Invite failed",
      );
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api(`/v1/memberships/${id}`, { method: "DELETE" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["members"] }),
  });

  return (
    <div>
      <header className="mb-8 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Members</h1>
          <p className="mt-1 text-sm text-zinc-500">
            {page?.meta.total ?? 0} seat(s) in use. Invites count against the plan limit.
          </p>
        </div>
      </header>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (email.trim()) invite.mutate(email.trim());
        }}
        className="mb-6 flex gap-3"
      >
        <label htmlFor="invite-email" className="sr-only">
          Email to invite
        </label>
        <input
          id="invite-email"
          type="email"
          required
          placeholder="teammate@example.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className="flex-1 rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-900"
        />
        <button
          type="submit"
          disabled={invite.isPending}
          className="rounded-lg bg-zinc-900 px-5 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50"
        >
          {invite.isPending ? "Inviting…" : "Invite"}
        </button>
      </form>

      {error && (
        <p role="alert" className="mb-6 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {error}
        </p>
      )}

      <div className="overflow-hidden rounded-xl border border-zinc-200">
        <table className="w-full text-sm">
          <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500">
            <tr>
              <th className="px-4 py-3 font-medium">Member</th>
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Roles</th>
              <th className="px-4 py-3 font-medium sr-only">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100">
            {(page?.data ?? []).map((m) => (
              <tr key={m.id}>
                <td className="px-4 py-3">
                  <p className="font-medium text-zinc-900">{m.display_name ?? "—"}</p>
                  <p className="text-xs text-zinc-400">{m.email ?? m.invited_email}</p>
                </td>
                <td className="px-4 py-3">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      m.status === "active"
                        ? "bg-emerald-50 text-emerald-700"
                        : "bg-zinc-100 text-zinc-600"
                    }`}
                  >
                    {m.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-zinc-600">{m.role_keys.join(", ") || "—"}</td>
                <td className="px-4 py-3 text-right">
                  <button
                    onClick={() => remove.mutate(m.id)}
                    className="text-xs text-zinc-400 underline hover:text-red-600"
                  >
                    Remove
                  </button>
                </td>
              </tr>
            ))}
            {(page?.data ?? []).length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-zinc-400">
                  No members yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
