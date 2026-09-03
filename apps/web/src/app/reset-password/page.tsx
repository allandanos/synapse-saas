"use client";

/* Set a new password with the emailed token (?reset=…). Tokens are
 * single-use and expire 30 minutes; all sessions die on success. */

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";

function ResetForm() {
  const params = useSearchParams();
  const router = useRouter();
  const token = params.get("reset") ?? "";
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      await api("/v1/auth/reset-password", {
        method: "POST",
        body: JSON.stringify({ token, password }),
      });
      router.push("/login?reset=done");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Reset failed");
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4">
        <p className="text-sm text-amber-800">
          This page needs a reset token from your email link.
        </p>
        <Link href="/forgot-password" className="mt-2 inline-block text-sm font-medium text-amber-700 underline">
          Request a new link
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="mt-8 space-y-4">
      <div>
        <label htmlFor="new-password" className="mb-1.5 block text-sm font-medium text-zinc-700">
          New password
        </label>
        <input
          id="new-password"
          type="password"
          required
          minLength={10}
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-zinc-900"
        />
        <p className="mt-1 text-xs text-zinc-400">At least 10 characters.</p>
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
        {busy ? "Resetting…" : "Set new password"}
      </button>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-zinc-50 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-900 text-sm font-bold text-white">
            S
          </div>
          <span className="font-semibold tracking-tight">Synapse</span>
        </div>

        <h1 className="text-2xl font-semibold tracking-tight">Choose a new password</h1>
        <p className="mt-1 text-sm text-zinc-500">
          All active sessions will be signed out once it&apos;s changed.
        </p>

        <Suspense fallback={<p className="mt-8 text-sm text-zinc-400">Loading…</p>}>
          <ResetForm />
        </Suspense>

        <p className="mt-6 text-sm text-zinc-500">
          <Link href="/login" className="font-medium text-zinc-900 underline">
            Back to sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
