"use client";

/* Client side of the runtime config: the root layout resolves it on the
 * server (runtime-config.server.ts) and hands it down through this provider. */

import { createContext, useContext, type ReactNode } from "react";
import { setApiUrl } from "./api";
import type { Branding } from "./branding";

export interface ClientRuntimeConfig {
  /** Public API origin, no trailing slash. */
  apiUrl: string;
  branding: Branding;
}

const RuntimeConfigContext = createContext<ClientRuntimeConfig | null>(null);

export function RuntimeConfigProvider({
  config,
  children,
}: {
  config: ClientRuntimeConfig;
  children: ReactNode;
}) {
  // Point the API client at the runtime URL during render, not in an effect:
  // child effects (AuthProvider's silent refresh) run before a parent's, so an
  // effect here would be too late. Idempotent; browser only — the server-side
  // module is shared across requests and never calls the API through it.
  if (typeof window !== "undefined") setApiUrl(config.apiUrl);

  return <RuntimeConfigContext.Provider value={config}>{children}</RuntimeConfigContext.Provider>;
}

export function useRuntimeConfig(): ClientRuntimeConfig {
  const config = useContext(RuntimeConfigContext);
  if (!config) throw new Error("useRuntimeConfig must be used inside <RuntimeConfigProvider>");
  return config;
}

export function useBranding(): Branding {
  return useRuntimeConfig().branding;
}
