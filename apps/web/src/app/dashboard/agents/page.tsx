"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot } from "lucide-react";
import Link from "next/link";
import { ApiError, api } from "@/lib/api";

interface Agent {
  id: string;
  slug: string;
  name: string;
  description: string | null;
  status: string;
  config: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** Create-form defaults: a JSON config the executing runtime owns. */
const EMPTY_CONFIG = '{\n  "model": "gpt-4o-mini",\n  "tools": []\n}';

export default function AgentsPage() {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [config, setConfig] = useState(EMPTY_CONFIG);

  const { data: agents, error, isLoading } = useQuery<Agent[], ApiError>({
    queryKey: ["agents"],
    queryFn: () => api<Agent[]>("/v1/agents"),
    retry: false,
  });

  const refresh = () => queryClient.invalidateQueries({ queryKey: ["agents"] });

  const create = useMutation({
    mutationFn: async () => {
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(config) as Record<string, unknown>;
      } catch {
        throw new Error("Config must be valid JSON");
      }
      return api<Agent>("/v1/agents", {
        method: "POST",
        body: JSON.stringify({ slug, name, config: parsed }),
      });
    },
    onSuccess: () => {
      setMessage(null);
      setSlug("");
      setName("");
      setConfig(EMPTY_CONFIG);
      refresh();
    },
    onError: (err) => setMessage(err instanceof Error ? err.message : "Create failed"),
  });

  const toggle = useMutation({
    mutationFn: async (agent: Agent) =>
      api<Agent>(`/v1/agents/${agent.id}/${agent.status === "active" ? "disable" : "enable"}`, {
        method: "POST",
      }),
    onSuccess: refresh,
    onError: (err) => setMessage(err instanceof Error ? err.message : "Status change failed"),
  });

  // Entitlement wall: free/starter orgs get the upgrade prompt, not an error dump
  if (error instanceof ApiError && error.status === 403) {
    const body = error.body as { available_in?: string[]; upgrade_url?: string };
    return (
      <div>
        <header className="mb-8">
          <h1 className="text-2xl font-semibold tracking-tight">Agents</h1>
        </header>
        <div className="rounded-xl border border-zinc-200 p-10 text-center">
          <Bot className="mx-auto h-10 w-10 text-zinc-300" aria-hidden />
          <h2 className="mt-4 text-lg font-semibold">AI Agents is a Pro feature</h2>
          <p className="mx-auto mt-2 max-w-md text-sm text-zinc-500">
            Register, gate, and meter org-scoped agents — with AI-token billing that rides your
            plan. Available on
            {(body.available_in ?? []).map((plan) => ` ${plan}`).toString() || " higher plans"}.
          </p>
          <Link
            href={body.upgrade_url ?? "/dashboard/billing"}
            className="mt-6 inline-block rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900"
          >
            Upgrade plan
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div>
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Agents</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Your org&apos;s agent registry — governance and billing. Execution happens in your
          agent runtime.
        </p>
      </header>

      {message && (
        <p role="alert" className="mb-6 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          {message}
        </p>
      )}

      <section
        aria-labelledby="register-h"
        className="mb-8 rounded-xl border border-zinc-200 p-6"
      >
        <h2 id="register-h" className="text-sm font-semibold uppercase tracking-wide text-zinc-500">
          Register agent
        </h2>
        <form
          className="mt-4 grid gap-4 md:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <div>
            <label htmlFor="agent-slug" className="mb-1 block text-sm font-medium text-zinc-700">
              Slug
            </label>
            <input
              id="agent-slug"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="support-bot"
              pattern="[a-z0-9][a-z0-9-]*"
              required
              minLength={2}
              maxLength={100}
              className="w-full rounded-lg border border-zinc-200 px-3 py-2 text-sm placeholder:text-zinc-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900"
            />
          </div>
          <div>
            <label htmlFor="agent-name" className="mb-1 block text-sm font-medium text-zinc-700">
              Name
            </label>
            <input
              id="agent-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Support Bot"
              required
              minLength={2}
              maxLength={200}
              className="w-full rounded-lg border border-zinc-200 px-3 py-2 text-sm placeholder:text-zinc-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900"
            />
          </div>
          <div className="md:col-span-2">
            <label htmlFor="agent-config" className="mb-1 block text-sm font-medium text-zinc-700">
              Config (JSON — owned by your agent runtime)
            </label>
            <textarea
              id="agent-config"
              value={config}
              onChange={(e) => setConfig(e.target.value)}
              rows={5}
              spellCheck={false}
              className="w-full rounded-lg border border-zinc-200 px-3 py-2 font-mono text-xs leading-relaxed focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900"
            />
          </div>
          <div className="md:col-span-2">
            <button
              type="submit"
              disabled={create.isPending}
              className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 disabled:opacity-50"
            >
              {create.isPending ? "Registering…" : "Register"}
            </button>
          </div>
        </form>
      </section>

      <section aria-labelledby="registry-h">
        <h2 id="registry-h" className="mb-4 text-sm font-semibold uppercase tracking-wide text-zinc-500">
          Registered agents
        </h2>
        <div className="overflow-hidden rounded-xl border border-zinc-200">
          <table className="w-full text-sm">
            <thead className="bg-zinc-50 text-left text-xs uppercase tracking-wide text-zinc-500">
              <tr>
                <th className="px-4 py-3 font-medium">Agent</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Registered</th>
                <th className="px-4 py-3 font-medium sr-only">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {(agents ?? []).map((agent) => (
                <tr key={agent.id}>
                  <td className="px-4 py-3">
                    <div className="font-medium text-zinc-900">{agent.name}</div>
                    <div className="font-mono text-xs text-zinc-400">{agent.slug}</div>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        agent.status === "active"
                          ? "bg-emerald-50 text-emerald-700"
                          : "bg-zinc-100 text-zinc-500"
                      }`}
                    >
                      {agent.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-zinc-600">
                    {new Date(agent.created_at).toLocaleDateString()}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      onClick={() => toggle.mutate(agent)}
                      disabled={toggle.isPending}
                      className="rounded-lg border border-zinc-200 px-2.5 py-1.5 text-xs font-medium text-zinc-600 transition-colors hover:border-zinc-400 hover:text-zinc-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-900 disabled:opacity-50"
                    >
                      {agent.status === "active" ? "Disable" : "Enable"}
                    </button>
                  </td>
                </tr>
              ))}
              {agents?.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-zinc-400">
                    {isLoading ? "Loading…" : "No agents registered yet."}
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
