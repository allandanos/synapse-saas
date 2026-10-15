/* Console permission map: which RBAC permission each dashboard route needs to
 * be read. Mirrors the backend routers; the source of a viewer's permissions is
 * `orgs[].permission_keys` on GET /v1/auth/me (what `require_permission`
 * enforces). Routes any org member may open are absent. */

export const ROUTE_PERMISSIONS: Readonly<Record<string, string>> = {
  "/dashboard/members": "member:read",
  "/dashboard/agents": "agents:read",
  "/dashboard/billing": "billing:read",
  "/dashboard/api-keys": "apikey:manage",
  // Lists keys; its snippets presume one.
  "/dashboard/developer": "apikey:manage",
  "/dashboard/audit": "audit:read",
  "/dashboard/webhooks": "webhook:manage",
};

// Longest first, so a nested route inherits the most specific gate.
const ROUTES_BY_LENGTH = Object.keys(ROUTE_PERMISSIONS).sort((a, b) => b.length - a.length);

/** The permission needed to read `pathname`, or undefined when any member may. */
export function requiredPermission(pathname: string): string | undefined {
  const route = ROUTES_BY_LENGTH.find(
    (key) => pathname === key || pathname.startsWith(`${key}/`),
  );
  return route === undefined ? undefined : ROUTE_PERMISSIONS[route];
}

/** Pure: platform admins pass every backend check; undefined = no gate. */
export function hasPermission(
  permissions: ReadonlySet<string>,
  isPlatformAdmin: boolean,
  permission?: string,
): boolean {
  return (
    permission === undefined ||
    isPlatformAdmin ||
    permissions.has("*") ||
    permissions.has(permission)
  );
}
