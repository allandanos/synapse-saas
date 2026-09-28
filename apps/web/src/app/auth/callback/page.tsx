"use client";

/* SSO landing: the API's OIDC callback set the httpOnly refresh cookie and
   bounced here. Turn it into an access token (silent refresh) and continue. */

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { refreshTokens } from "@/lib/api";

function safeReturnTo(raw: string | null): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/dashboard";
}

function CallbackInner() {
  const router = useRouter();
  const params = useSearchParams();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const ok = await refreshTokens();
      if (cancelled) return;
      if (ok) {
        // Full navigation so the auth provider re-bootstraps from the fresh session
        window.location.replace(safeReturnTo(params.get("return_to")));
      } else {
        setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [params, router]);

  return (
    <main className="flex min-h-screen items-center justify-center bg-zinc-50 px-4">
      <div className="w-full max-w-sm text-center">
        {failed ? (
          <>
            <h1 className="text-xl font-semibold tracking-tight">Sign-in did not complete</h1>
            <p className="mt-2 text-sm text-zinc-500">
              The identity provider signed you in, but the session could not be established.
            </p>
            <a href="/login" className="mt-6 inline-block text-sm font-medium text-zinc-900 underline">
              Back to sign in
            </a>
          </>
        ) : (
          <p className="text-sm text-zinc-500">Finishing sign-in…</p>
        )}
      </div>
    </main>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={null}>
      <CallbackInner />
    </Suspense>
  );
}
