"use client";

/* "You've joined {org}" after an invitation is accepted (/dashboard?joined=<id>).
 * Renders only when the id is one of the caller's memberships. */

import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle2, Compass, X } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { useTourControls } from "@/components/tour";

function JoinedBannerInner() {
  const params = useSearchParams();
  const router = useRouter();
  const { me } = useAuth();
  const tour = useTourControls();
  const joinedId = params.get("joined");
  const org = joinedId ? me?.orgs.find((o) => o.id === joinedId) : undefined;
  if (!org) return null;

  return (
    <div
      role="status"
      className="mb-6 flex items-start gap-3 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3"
    >
      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-hidden />
      <p className="flex-1 text-sm text-emerald-900">
        You&apos;ve joined <span className="font-semibold">{org.name}</span>
      </p>
      {/* Invitees are never auto-interrupted; the tour is offered here instead. */}
      <button
        type="button"
        onClick={() => {
          tour.start();
          router.replace("/dashboard");
        }}
        className="-my-0.5 inline-flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-sm font-medium text-emerald-800 hover:bg-emerald-100 hover:text-emerald-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
      >
        <Compass className="h-3.5 w-3.5" aria-hidden />
        Take the tour
      </button>
      <button
        type="button"
        onClick={() => router.replace("/dashboard")}
        aria-label="Dismiss"
        className="-m-1 rounded-md p-1 text-emerald-700 hover:bg-emerald-100 hover:text-emerald-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500"
      >
        <X className="h-4 w-4" aria-hidden />
      </button>
    </div>
  );
}

export function JoinedBanner() {
  return (
    <Suspense fallback={null}>
      <JoinedBannerInner />
    </Suspense>
  );
}
