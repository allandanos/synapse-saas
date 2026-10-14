"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth-context";
import { useBranding } from "@/lib/runtime-config";
import { useInvitePreview } from "@/lib/use-invite-preview";
import {
  AcceptFailedAlert,
  InviteInvalidNotice,
  errorMessage,
  joinedHref,
} from "@/components/invite-notices";

const INPUT_CLASS =
  "w-full rounded-lg border border-zinc-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary";

function RegisterForm() {
  const { me, register, acceptInvite } = useAuth();
  const { name: productName } = useBranding();
  const router = useRouter();
  const params = useSearchParams();
  const inviteToken = params.get("invite") ?? "";
  const invite = useInvitePreview(inviteToken);
  const preview = invite.status === "ready" ? invite.preview : null;

  const [displayName, setDisplayName] = useState("");
  // null = untouched: shows the invited address until the user edits it.
  const [emailInput, setEmailInput] = useState<string | null>(null);
  const email = emailInput ?? preview?.invited_email ?? "";
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [acceptError, setAcceptError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function join() {
    try {
      const org = await acceptInvite(inviteToken);
      router.push(joinedHref(org.id));
    } catch (err) {
      setAcceptError(errorMessage(err, "The invitation could not be accepted"));
    }
  }

  async function onAcceptSignedIn() {
    setBusy(true);
    setAcceptError(null);
    await join();
    setBusy(false);
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setAcceptError(null);
    try {
      await register(email, password, displayName);
    } catch (err) {
      setError(errorMessage(err, "Registration failed"));
      setBusy(false);
      return;
    }
    if (inviteToken) {
      await join();
    } else {
      router.push("/onboarding");
    }
    setBusy(false);
  }

  if (invite.status === "invalid") return <InviteInvalidNotice />;

  const loginHref = inviteToken ? `/login?invite=${encodeURIComponent(inviteToken)}` : "/login";

  return (
    <>
      {preview ? (
        <>
          <h1 className="text-2xl font-semibold tracking-tight">
            Join <span className="text-primary">{preview.organization.name}</span>
          </h1>
          <p className="mt-1 text-sm text-zinc-500">
            Invited as{" "}
            <span className="font-medium text-zinc-900">
              {preview.role_keys.join(", ") || "member"}
            </span>
          </p>
        </>
      ) : (
        <>
          <h1 className="text-2xl font-semibold tracking-tight">Create your account</h1>
          <p className="mt-1 text-sm text-zinc-500">Get started with {productName}.</p>
        </>
      )}

      {invite.status === "error" && (
        <p role="alert" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
          Could not load the invitation: {invite.message}
        </p>
      )}

      {me && inviteToken && (
        <div className="mt-6 rounded-lg border border-zinc-200 bg-zinc-50 p-4">
          <p className="text-sm text-zinc-600">
            You&apos;re signed in as <span className="font-medium text-zinc-900">{me.email}</span>.
          </p>
          <button
            type="button"
            onClick={onAcceptSignedIn}
            disabled={busy}
            className="mt-3 w-full rounded-lg bg-primary py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 disabled:opacity-50"
          >
            {busy ? "Joining…" : `Accept as ${me.email}`}
          </button>
          <p className="mt-3 text-xs text-zinc-400">Or create a separate account below.</p>
        </div>
      )}

      <form onSubmit={onSubmit} className="mt-8 space-y-4">
        <div>
          <label htmlFor="name" className="mb-1.5 block text-sm font-medium text-zinc-700">
            Name
          </label>
          <input
            id="name"
            required
            autoComplete="name"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className={INPUT_CLASS}
          />
        </div>
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
            onChange={(e) => setEmailInput(e.target.value)}
            className={INPUT_CLASS}
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
            minLength={10}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={INPUT_CLASS}
          />
          <p className="mt-1 text-xs text-zinc-400">At least 10 characters.</p>
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
          {busy ? "Creating…" : preview ? "Create account and join" : "Create account"}
        </button>
      </form>

      <p className="mt-6 text-sm text-zinc-500">
        Already registered?{" "}
        <Link href={loginHref} className="font-medium text-zinc-900 underline">
          Sign in
        </Link>
      </p>
    </>
  );
}


export default function RegisterPage() {
  return (
    <Suspense fallback={null}>
      <RegisterForm />
    </Suspense>
  );
}
