"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

export default function OnboardingPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api("/v1/orgs", {
        method: "POST",
        body: JSON.stringify({ name, slug: slug || undefined }),
      });
      router.push("/dashboard");
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the organization");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-zinc-50 px-4">
      <div className="w-full max-w-md">
        <h1 className="text-2xl font-semibold tracking-tight">Create your organization</h1>
        <p className="mt-1 text-sm text-zinc-500">
          You&apos;ll be the owner. A Free-plan subscription is provisioned automatically.
        </p>

        <form onSubmit={onSubmit} className="mt-8 space-y-4">
          <div>
            <label htmlFor="org-name" className="mb-1.5 block text-sm font-medium text-zinc-700">
              Organization name
            </label>
            <input
              id="org-name"
              required
              minLength={2}
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-900"
            />
          </div>
          <div>
            <label htmlFor="org-slug" className="mb-1.5 block text-sm font-medium text-zinc-700">
              Slug <span className="font-normal text-zinc-400">(optional)</span>
            </label>
            <input
              id="org-slug"
              pattern="[a-z0-9][a-z0-9-]*"
              placeholder="acme"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-900"
            />
            <p className="mt-1 text-xs text-zinc-400">
              Lowercase letters, digits, dashes. Auto-generated from the name if blank.
            </p>
          </div>

          {error && (
            <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-zinc-900 py-2.5 text-sm font-medium text-white hover:bg-zinc-700 disabled:opacity-50"
          >
            {busy ? "Creating…" : "Create organization"}
          </button>
        </form>
      </div>
    </main>
  );
}
