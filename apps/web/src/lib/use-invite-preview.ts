"use client";

/* Invitation preview for /register?invite= and /login?invite=: names the org
 * before the invite is accepted. Unauthenticated; 404 means unknown or used. */

import { useQuery } from "@tanstack/react-query";
import { api, ApiError, type InvitePreview } from "./api";

export type InvitePreviewState =
  | { status: "none" }
  | { status: "loading" }
  | { status: "invalid" }
  | { status: "error"; message: string }
  | { status: "ready"; preview: InvitePreview };

export function useInvitePreview(token: string): InvitePreviewState {
  const query = useQuery({
    queryKey: ["invite-preview", token],
    queryFn: () =>
      api<InvitePreview>(`/v1/auth/invite?token=${encodeURIComponent(token)}`),
    enabled: token.length > 0,
    retry: false,
    staleTime: Infinity,
  });

  if (!token) return { status: "none" };
  if (query.isPending) return { status: "loading" };
  if (query.isError) {
    const err = query.error;
    // 404 invite_not_found (unknown/used) and 422 (malformed) both mean the link is dead.
    if (err instanceof ApiError && (err.status === 404 || err.status === 422)) {
      return { status: "invalid" };
    }
    return { status: "error", message: err.message };
  }
  return { status: "ready", preview: query.data };
}
