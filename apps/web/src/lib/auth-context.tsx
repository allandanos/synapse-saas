"use client";

/* Auth + org context: access token in memory, silent refresh on mount,
 * active org in a cookie mirrored to X-Org-Id.
 *
 * Every mutation that changes org membership reloads the session and selects
 * the right org before it resolves. No function here navigates — pages own
 * navigation, so they can act on the returned Me/Org. */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import {
  api,
  refreshTokens,
  setAccessToken,
  setOrgId,
  type Entitlements,
  type Me,
  type Org,
} from "./api";
import { hasPermission } from "./permissions";

interface AuthState {
  me: Me | null;
  entitlements: Entitlements | null;
  activeOrgId: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<Me>;
  register: (email: string, password: string, displayName: string) => Promise<Me>;
  logout: () => Promise<void>;
  switchOrg: (orgId: string) => Promise<void>;
  createOrg: (name: string, slug?: string) => Promise<Org>;
  acceptInvite: (token: string) => Promise<Org>;
  hasFeature: (feature: string) => boolean;
  /** The active org's permission keys; empty without an org. */
  permissions: ReadonlySet<string>;
  /** True when the viewer may use `permission` in the active org (undefined = ungated). */
  can: (permission?: string) => boolean;
  /** Merges top-level preference keys (server-side) and adopts the returned profile. */
  updatePreferences: (patch: Record<string, unknown>) => Promise<Me>;
}

interface TokenResponse {
  tokens: { access_token: string };
}

const ORG_COOKIE = "synapse_org";
const ORG_COOKIE_MAX_AGE = 2_592_000; // 30 days

function readOrgCookie(): string | undefined {
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${ORG_COOKIE}=`))
    ?.split("=")[1];
}

function writeOrgCookie(orgId: string | null) {
  document.cookie = orgId
    ? `${ORG_COOKIE}=${orgId}; path=/; max-age=${ORG_COOKIE_MAX_AGE}; samesite=lax`
    : `${ORG_COOKIE}=; path=/; max-age=0`;
}

/* Org pick order: explicitly preferred → cookie → first membership. */
function pickOrg(orgs: Org[], preferredOrgId?: string | null): string | null {
  const byId = (id: string | null | undefined) =>
    id ? orgs.find((o) => o.id === id)?.id : undefined;
  return byId(preferredOrgId) ?? byId(readOrgCookie()) ?? orgs[0]?.id ?? null;
}

function findOrg(profile: Me, orgId: string): Org {
  const org = profile.orgs.find((o) => o.id === orgId);
  if (!org) throw new Error("The organization is not in your memberships yet — reload and try again.");
  return org;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [entitlements, setEntitlements] = useState<Entitlements | null>(null);
  const [activeOrgId, setActiveOrgId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const queryClient = useQueryClient();

  const clearSession = useCallback(() => {
    setAccessToken(null);
    setOrgId(null);
    setMe(null);
    setEntitlements(null);
    setActiveOrgId(null);
  }, []);

  /* A failed entitlements call never signs the user out: FeatureGate simply
   * reports no features until the next successful load. */
  const fetchEntitlementsOrNull = useCallback(async (): Promise<Entitlements | null> => {
    try {
      return await api<Entitlements>("/v1/entitlements");
    } catch {
      return null;
    }
  }, []);

  /* Loads /me, selects the org, fetches its entitlements. Returns the profile,
   * or null when there is no refreshable session. */
  const loadSession = useCallback(
    async (preferredOrgId?: string | null): Promise<Me | null> => {
      const ok = await refreshTokens();
      if (!ok) {
        clearSession();
        return null;
      }
      const profile = await api<Me>("/v1/auth/me");
      const org = pickOrg(profile.orgs, preferredOrgId);
      setOrgId(org);
      writeOrgCookie(org);
      // Set together: the dashboard guard never sees `me` without its org.
      setMe(profile);
      setActiveOrgId(org);
      setEntitlements(org ? await fetchEntitlementsOrNull() : null);
      return profile;
    },
    [clearSession, fetchEntitlementsOrNull],
  );

  /* Same as loadSession, but a just-authenticated caller must get a profile. */
  const requireSession = useCallback(
    async (preferredOrgId?: string | null): Promise<Me> => {
      const profile = await loadSession(preferredOrgId);
      if (!profile) throw new Error("Your session could not be established — sign in again.");
      return profile;
    },
    [loadSession],
  );

  useEffect(() => {
    // Session bootstrap is asynchronous (refresh → /me → entitlements); run it
    // as a callback so every setState happens after the effect, never during it.
    let active = true;
    Promise.resolve()
      .then(() => loadSession())
      // A failed /me after a good refresh leaves the session signed out
      // (me stays null) — not an unhandled rejection. Entitlement failures
      // are absorbed inside loadSession.
      .catch(() => undefined)
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [loadSession]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await api<TokenResponse>("/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setAccessToken(res.tokens.access_token);
      return requireSession();
    },
    [requireSession],
  );

  const register = useCallback(
    async (email: string, password: string, displayName: string) => {
      const res = await api<TokenResponse>("/v1/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password, display_name: displayName }),
      });
      setAccessToken(res.tokens.access_token);
      return requireSession();
    },
    [requireSession],
  );

  const createOrg = useCallback(
    async (name: string, slug?: string) => {
      const created = await api<{ id: string }>("/v1/orgs", {
        method: "POST",
        body: JSON.stringify({ name, slug: slug || undefined }),
      });
      const profile = await requireSession(created.id);
      return findOrg(profile, created.id);
    },
    [requireSession],
  );

  const acceptInvite = useCallback(
    async (token: string) => {
      const res = await api<{ organization_id: string; status: string }>(
        "/v1/auth/accept-invite",
        { method: "POST", body: JSON.stringify({ token }) },
      );
      const profile = await requireSession(res.organization_id);
      return findOrg(profile, res.organization_id);
    },
    [requireSession],
  );

  const logout = useCallback(async () => {
    // Best effort: the local session is cleared even if the API call fails.
    await api("/v1/auth/logout", { method: "POST" }).catch(() => undefined);
    clearSession();
    writeOrgCookie(null);
    queryClient.clear();
    router.push("/login");
  }, [clearSession, queryClient, router]);

  const switchOrg = useCallback(async (orgId: string) => {
    const res = await api<{ access_token: string }>("/v1/auth/switch-org", {
      method: "POST",
      body: JSON.stringify({ organization_id: orgId }),
    });
    // Adopt the org-scoped token before any org-scoped request goes out, and
    // move the UI with the header at once: activeOrgId never lags the requests.
    setAccessToken(res.access_token);
    setOrgId(orgId);
    setActiveOrgId(orgId);
    writeOrgCookie(orgId);
    try {
      setEntitlements(await api<Entitlements>("/v1/entitlements"));
    } catch (err) {
      setEntitlements(null);
      throw err; // the switcher surfaces it; the org switch itself stands
    }
  }, []);

  const hasFeature = useCallback(
    (feature: string) => entitlements?.features.includes(feature) ?? false,
    [entitlements],
  );

  // Memo on the joined keys, not the array: `me` is replaced on every preferences save.
  const permissionKey =
    me?.orgs.find((o) => o.id === activeOrgId)?.permission_keys?.join(",") ?? "";
  const permissions = useMemo<ReadonlySet<string>>(
    () => new Set(permissionKey ? permissionKey.split(",") : []),
    [permissionKey],
  );
  const isPlatformAdmin = me?.is_platform_admin ?? false;
  const can = useCallback(
    (permission?: string) => hasPermission(permissions, isPlatformAdmin, permission),
    [permissions, isPlatformAdmin],
  );

  const updatePreferences = useCallback(async (patch: Record<string, unknown>) => {
    const profile = await api<Me>("/v1/auth/me", {
      method: "PATCH",
      body: JSON.stringify({ preferences: patch }),
    });
    // Functional guard: a late response never resurrects a session after logout().
    setMe((prev) => (prev && prev.id === profile.id ? profile : prev));
    return profile;
  }, []);

  const value = useMemo(
    () => ({
      me,
      entitlements,
      activeOrgId,
      loading,
      login,
      register,
      logout,
      switchOrg,
      createOrg,
      acceptInvite,
      hasFeature,
      permissions,
      can,
      updatePreferences,
    }),
    [
      me,
      entitlements,
      activeOrgId,
      loading,
      login,
      register,
      logout,
      switchOrg,
      createOrg,
      acceptInvite,
      hasFeature,
      permissions,
      can,
      updatePreferences,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
