"use client";

/* Auth + org context: access token in memory, silent refresh on mount,
 * active org in a cookie mirrored to X-Org-Id. */

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
import {
  api,
  refreshTokens,
  setAccessToken,
  setOrgId,
  type Entitlements,
  type Me,
} from "./api";

interface AuthState {
  me: Me | null;
  entitlements: Entitlements | null;
  activeOrgId: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => Promise<void>;
  switchOrg: (orgId: string) => Promise<void>;
  hasFeature: (feature: string) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [entitlements, setEntitlements] = useState<Entitlements | null>(null);
  const [activeOrgId, setActiveOrgId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  const loadSession = useCallback(async () => {
    const ok = await refreshTokens();
    if (!ok) {
      setMe(null);
      setEntitlements(null);
      setActiveOrgId(null);
      return false;
    }
    const profile = await api<Me>("/v1/auth/me");
    setMe(profile);

    const cookieOrg = document.cookie
      .split("; ")
      .find((c) => c.startsWith("synapse_org="))
      ?.split("=")[1];
    const org =
      profile.orgs.find((o) => o.id === cookieOrg)?.id ?? profile.orgs[0]?.id ?? null;
    setActiveOrgId(org);
    setOrgId(org);
    if (org) document.cookie = `synapse_org=${org}; path=/; max-age=2592000; samesite=lax`;

    if (org) {
      const ent = await api<Entitlements>("/v1/entitlements");
      setEntitlements(ent);
    }
    return true;
  }, []);

  useEffect(() => {
    loadSession().finally(() => setLoading(false));
  }, [loadSession]);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await api<{ tokens: { access_token: string } }>("/v1/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });
      setAccessToken(res.tokens.access_token);
      await loadSession();
      router.push("/dashboard");
    },
    [loadSession, router],
  );

  const register = useCallback(
    async (email: string, password: string, displayName: string) => {
      const res = await api<{ tokens: { access_token: string } }>("/v1/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password, display_name: displayName }),
      });
      setAccessToken(res.tokens.access_token);
      await loadSession();
      router.push("/onboarding");
    },
    [loadSession, router],
  );

  const logout = useCallback(async () => {
    await api("/v1/auth/logout", { method: "POST" }).catch(() => undefined);
    setAccessToken(null);
    setOrgId(null);
    setMe(null);
    setEntitlements(null);
    document.cookie = "synapse_org=; path=/; max-age=0";
    router.push("/login");
  }, [router]);

  const switchOrg = useCallback(
    async (orgId: string) => {
      await api("/v1/auth/switch-org", {
        method: "POST",
        body: JSON.stringify({ organization_id: orgId }),
      });
      document.cookie = `synapse_org=${orgId}; path=/; max-age=2592000; samesite=lax`;
      setActiveOrgId(orgId);
      setOrgId(orgId);
      const ent = await api<Entitlements>("/v1/entitlements");
      setEntitlements(ent);
      router.refresh();
    },
    [router],
  );

  const hasFeature = useCallback(
    (feature: string) => entitlements?.features.includes(feature) ?? false,
    [entitlements],
  );

  const value = useMemo(
    () => ({ me, entitlements, activeOrgId, loading, login, register, logout, switchOrg, hasFeature }),
    [me, entitlements, activeOrgId, loading, login, register, logout, switchOrg, hasFeature],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
