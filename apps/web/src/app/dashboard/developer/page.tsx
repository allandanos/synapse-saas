"use client";

/* Developer portal: quickstart with the caller's real key, live API probe,
   flag checker, and copy-ready snippets. */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, Copy, Flag, Terminal } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  last_used_at: string | null;
  revoked_at: string | null;
}

interface FlagCheck {
  key: string;
  enabled: boolean;
}

function Snippet({ label, code }: { label: string; code: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard unavailable (insecure context) — user selects manually
    }
  }

  return (
    <div className="rounded-xl border border-zinc-200">
      <div className="flex items-center justify-between border-b border-zinc-200 bg-zinc-50 px-4 py-2">
        <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">{label}</span>
        <button
          onClick={copy}
          className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-zinc-500 hover:bg-zinc-100 hover:text-zinc-900"
          aria-label={`Copy ${label} snippet`}
        >
          {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="overflow-x-auto px-4 py-3 text-xs leading-relaxed text-zinc-800">
        <code>{code}</code>
      </pre>
    </div>
  );
}

export default function DeveloperPage() {
  const { activeOrgId, entitlements } = useAuth();
  const [flagKey, setFlagKey] = useState("");
  const [flagResult, setFlagResult] = useState<FlagCheck | null>(null);
  const [flagError, setFlagError] = useState<string | null>(null);
  const [probeStatus, setProbeStatus] = useState<number | null>(null);

  const { data: keys } = useQuery({
    queryKey: ["api-keys"],
    queryFn: () => api<ApiKey[]>("/v1/api-keys"),
  });

  const activeKey = (keys ?? []).find((k) => k.revoked_at === null);

  const probe = useMutation({
    mutationFn: () => api<{ status: string }>("/v1/meta"),
    onSuccess: () => setProbeStatus(200),
    onError: () => setProbeStatus(0),
  });

  const checkFlag = useMutation({
    mutationFn: (key: string) =>
      api<FlagCheck>(`/v1/feature-flags/check/${encodeURIComponent(key)}`),
    onSuccess: (result) => {
      setFlagResult(result);
      setFlagError(null);
    },
    onError: (err) => {
      setFlagError(err instanceof Error ? err.message : "Check failed");
      setFlagResult(null);
    },
  });

  const apiBase =
    typeof window !== "undefined" ? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000" : "";
  const keyPlaceholder = activeKey ? "sk_…your secret from API keys" : "sk_your_key_here";
  const hasApiAccess = entitlements?.features.includes("api_access") ?? false;

  const curlSnippet = `curl ${apiBase}/v1/usage/summary \\
  -H "Authorization: Bearer ${keyPlaceholder}"`;

  const tsSnippet = `const res = await fetch("${apiBase}/v1/usage/summary", {
  headers: { Authorization: "Bearer ${keyPlaceholder}" },
});
const usage = await res.json();`;

  const pySnippet = `import httpx

client = httpx.Client(
    base_url="${apiBase}",
    headers={"Authorization": "Bearer ${keyPlaceholder}"},
)
usage = client.get("/v1/usage/summary").json()`;

  return (
    <div>
      <header className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight">Developer portal</h1>
        <p className="mt-1 text-sm text-zinc-500">
          Programmatic access to <span className="font-medium text-zinc-900">{activeOrgId ? "this organization" : "your org"}</span> —
          authenticate any request with an API key. Live reference:{" "}
          <a
            href={`${apiBase}/docs`}
            target="_blank"
            rel="noreferrer"
            className="font-medium underline"
          >
            OpenAPI docs
          </a>
        </p>
      </header>

      {!hasApiAccess && (
        <p className="mb-6 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
          The current plan does not include <code>api_access</code> — upgrade to call the API.
        </p>
      )}

      {activeKey ? (
        <p className="mb-6 rounded-lg bg-zinc-100 px-3 py-2 text-sm text-zinc-700">
          Using key <code className="font-mono">{activeKey.prefix}…</code> ({activeKey.name})
          {activeKey.scopes.length > 0 && <> — scopes: {activeKey.scopes.join(", ")}</>}
        </p>
      ) : (
        <p className="mb-6 rounded-lg bg-zinc-50 px-3 py-2 text-sm text-zinc-500">
          No active API key — create one on the{" "}
          <a href="/dashboard/api-keys" className="underline">
            API keys
          </a>{" "}
          page, then return here for ready-to-use snippets.
        </p>
      )}

      <div className="space-y-4">
        <Snippet label="curl" code={curlSnippet} />
        <Snippet label="TypeScript" code={tsSnippet} />
        <Snippet label="Python" code={pySnippet} />
      </div>

      <section aria-labelledby="probe-h" className="mt-10">
        <h2 id="probe-h" className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-zinc-500">
          <Terminal className="h-4 w-4" /> Live probe
        </h2>
        <p className="mb-3 text-sm text-zinc-500">
          Verifies your console session can reach the API right now (uses your logged-in credentials, not a key).
        </p>
        <div className="flex items-center gap-3">
          <button
            onClick={() => probe.mutate()}
            disabled={probe.isPending}
            className="rounded-lg bg-zinc-900 px-4 py-2 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50"
          >
            {probe.isPending ? "Probing…" : "Send GET /v1/meta"}
          </button>
          {probeStatus !== null && (
            <span
              className={`rounded-full px-3 py-1 text-xs font-medium ${
                probeStatus === 200 ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"
              }`}
              role="status"
            >
              {probeStatus === 200 ? "reachable · 200" : "unreachable"}
            </span>
          )}
        </div>
      </section>

      <section aria-labelledby="flag-h" className="mt-10">
        <h2 id="flag-h" className="mb-3 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-zinc-500">
          <Flag className="h-4 w-4" /> Flag checker
        </h2>
        <p className="mb-3 text-sm text-zinc-500">
          Resolve a feature flag for this organization (overrides and rollout included).
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (flagKey.trim()) checkFlag.mutate(flagKey.trim());
          }}
          className="flex items-center gap-3"
        >
          <label htmlFor="flag-key-input" className="sr-only">
            Flag key
          </label>
          <input
            id="flag-key-input"
            placeholder="e.g. new-editor"
            value={flagKey}
            onChange={(e) => setFlagKey(e.target.value)}
            className="w-64 rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-900"
          />
          <button
            type="submit"
            disabled={checkFlag.isPending}
            className="rounded-lg border border-zinc-300 px-4 py-2 text-sm font-medium text-zinc-700 hover:bg-zinc-50 disabled:opacity-50"
          >
            {checkFlag.isPending ? "Checking…" : "Check"}
          </button>
        </form>
        {flagResult && (
          <p role="status" className="mt-3 text-sm">
            <code className="font-mono">{flagResult.key}</code>{" "}
            <span
              className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                flagResult.enabled ? "bg-emerald-50 text-emerald-700" : "bg-zinc-100 text-zinc-500"
              }`}
            >
              {flagResult.enabled ? "enabled" : "disabled"}
            </span>
          </p>
        )}
        {flagError && (
          <p role="alert" className="mt-3 text-sm text-red-600">
            {flagError}
          </p>
        )}
      </section>
    </div>
  );
}
