/* Shared notices for the join-by-invite flow on /register and /login. */

import Link from "next/link";

export function InviteInvalidNotice() {
  return (
    <div role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-4">
      <p className="text-sm font-medium text-amber-900">
        This invitation is invalid or was already used
      </p>
      <p className="mt-1 text-sm text-amber-800">
        Ask an owner of the organization to send a new invitation.
      </p>
      <div className="mt-3 flex gap-4 text-sm">
        <Link href="/login" className="font-medium text-amber-900 underline underline-offset-2 hover:text-amber-950">
          Sign in
        </Link>
        <Link href="/register" className="font-medium text-amber-900 underline underline-offset-2 hover:text-amber-950">
          Create an account
        </Link>
      </div>
    </div>
  );
}

/* The account/session exists but joining failed: say so and offer a way on. */
export function AcceptFailedAlert({ message }: { message: string }) {
  return (
    <div role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
      <p>Could not accept the invitation: {message}</p>
      <Link href="/dashboard" className="mt-1 inline-block font-medium underline underline-offset-2 hover:text-red-900">
        Continue to your dashboard
      </Link>
    </div>
  );
}

export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

export function joinedHref(orgId: string): string {
  return `/dashboard?joined=${encodeURIComponent(orgId)}`;
}
