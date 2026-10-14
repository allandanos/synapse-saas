"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { useRuntimeConfig } from "@/lib/runtime-config";
import { useInvitePreview } from "@/lib/use-invite-preview";
import {
  AcceptFailedAlert,
  InviteInvalidNotice,
  errorMessage,
  joinedHref,
} from "@/components/invite-notices";

function LoginForm() {
  const { login, acceptInvite } = useAuth();
  const { apiUrl } = useRuntimeConfig();
  const router = useRouter();
  const params = useSearchParams();
  const resetDone = params.get("reset") === "done";
  const inviteToken = params.get("invite") ?? "";
  const invite = useInvitePreview(inviteToken);
  const [ssoEnabled, setSsoEnabled] = useState(false);

  useEffect(() => {
    // /v1/meta is public: it tells the console which identity provider is active
    api<{ identity_provider: string }>("/v1/meta")
      .then((meta) => setSsoEnabled(meta.identity_provider === "keycloak"))
      .catch(() => setSsoEnabled(false));
  }, []);

  const ssoHref = `${apiUrl}/v1/auth/oidc/start?return_to=${encodeURIComponent(
    params.get("return_to") ?? "/dashboard",
  )}`;
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [acceptError, setAcceptError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // A dead invite link still lets the user sign in; it just isn't accepted.
  const shouldAccept = inviteToken !== "" && invite.status !== "invalid";

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setAcceptError(null);
    try {
      await login(email, password);
    } catch (err) {
      setError(errorMessage(err, "Sign-in failed"));
      setBusy(false);
      return;
    }
    if (!shouldAccept) {
      router.push("/dashboard");
      return;
    }
    try {
      const org = await acceptInvite(inviteToken);
      router.push(joinedHref(org.id));
    } catch (err) {
      setAcceptError(errorMessage(err, "The invitation could not be accepted"));
      setBusy(false);
    }
  }

  const registerHref = inviteToken
    ? `/register?invite=${encodeURIComponent(inviteToken)}`
    : "/register";

  return (
    <>
      {resetDone && (
        <p className="mb-4 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          Password updated — sign in with your new password.
        </p>
      )}
      {invite.status === "ready" && (
        <p className="mb-4 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          Sign in to accept your invitation to{" "}
          <span className="font-semibold">{invite.preview.organization.name}</span>
        </p>
      )}
      {invite.status === "invalid" && (
        <div className="mb-4">
          <InviteInvalidNotice />
        </div>
      )}
      {invite.status === "error" && (
        <p role="alert" className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          Could not load the invitation: {invite.message}
        </p>
      )}
      <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
      <p className="mt-1 text-sm text-zinc-500">Welcome back to your console.</p>

      {ssoEnabled && (
        <div className="mt-8">
          <a
            href={ssoHref}
            data-testid="sso-button"
            className="flex w-full items-center justify-center rounded-lg border border-primary py-2.5 text-sm font-medium text-primary hover:bg-zinc-100"
          >
            Continue with single sign-on
          </a>
          <div className="my-4 flex items-center gap-3 text-xs uppercase tracking-wide text-zinc-400">
            <span className="h-px flex-1 bg-zinc-200" />
            or
            <span className="h-px flex-1 bg-zinc-200" />
          </div>
        </div>
      )}

      <form onSubmit={onSubmit} className={ssoEnabled ? "space-y-4" : "mt-8 space-y-4"}>
        <div>
          <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-zinc-700">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        <div>
          <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-zinc-700">
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>

        {error && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}
        {acceptError && <AcceptFailedAlert message={acceptError} />}

        <button
          type="submit"
          disabled={busy}
          className="w-full rounded-lg bg-primary py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <div className="mt-6 flex items-center justify-between text-sm">
        <span className="text-zinc-500">
          No account?{" "}
          <Link href={registerHref} className="font-medium text-zinc-900 underline">
            Create one
          </Link>
        </span>
        <Link href="/forgot-password" className="text-zinc-500 underline hover:text-zinc-900">
          Forgot password?
        </Link>
      </div>
    </>
  );
}


export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
