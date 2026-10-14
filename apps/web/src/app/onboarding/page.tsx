"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth-context";

export default function OnboardingPage() {
  const router = useRouter();
  const { me, loading, createOrg } = useAuth();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const hasOrgs = (me?.orgs.length ?? 0) > 0;

  useEffect(() => {
    if (!loading && !me) router.replace("/login");
  }, [loading, me, router]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      // createOrg reloads the session with the new org active before resolving,
      // so the dashboard mounts with an org already selected.
      await createOrg(name, slug || undefined);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the organization");
      setBusy(false);
    }
  }

  if (loading || !me) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-zinc-50">
        <p className="text-sm text-zinc-400">Loading…</p>
      </main>
    );
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-zinc-50 px-4">
      <div className="w-full max-w-md">
        {hasOrgs && (
          <Link
            href="/dashboard"
            className="mb-6 inline-flex items-center gap-1 rounded-md text-sm text-zinc-500 hover:text-zinc-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <span aria-hidden>←</span> Back to dashboard
          </Link>
        )}
        <h1 className="text-2xl font-semibold tracking-tight">
          {hasOrgs ? "Create another organization" : "Create your organization"}
        </h1>
        <p className="mt-1 text-sm text-zinc-500">
          {hasOrgs
            ? "This will be a second organization you own. "
            : "You\u2019ll be the owner. "}
          A Free-plan subscription is provisioned automatically.
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
              className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
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
              className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
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
            className="w-full rounded-lg bg-primary py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {busy ? "Creating…" : "Create organization"}
          </button>
        </form>
      </div>
    </main>
  );
}
