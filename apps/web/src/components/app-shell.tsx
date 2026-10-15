"use client";

/* App shell: sidebar nav + org switcher + user menu. Server-style semantic layout.
 * Below md the sidebar collapses into a top bar with a disclosure menu. */

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Bot,
  Building2,
  Code2,
  CreditCard,
  KeyRound,
  Menu,
  Plus,
  ScrollText,
  Settings,
  ShieldCheck,
  Users,
  Webhook,
  X,
} from "lucide-react";
import { BrandMark } from "@/components/brand-mark";
import { TourButton } from "@/components/tour";
import { useAuth } from "@/lib/auth-context";
import { ROUTE_PERMISSIONS } from "@/lib/permissions";

/* `tour` names the link's product-tour anchor (`data-tour="nav-<tour>"`, see
 * components/tour/steps.tsx). NextStep scrolls anchors into view with
 * scrollIntoView: a fork with a sticky header should add `scroll-mt-*` here. */
const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: BarChart3, tour: "dashboard" },
  { href: "/dashboard/members", label: "Members", icon: Users, tour: "members" },
  { href: "/dashboard/agents", label: "Agents", icon: Bot, tour: "agents" },
  { href: "/dashboard/billing", label: "Billing", icon: CreditCard, tour: "billing" },
  { href: "/dashboard/api-keys", label: "API keys", icon: KeyRound, tour: "api-keys" },
  { href: "/dashboard/developer", label: "Developer", icon: Code2, tour: "developer" },
  { href: "/dashboard/usage", label: "Usage", icon: BarChart3, tour: "usage" },
  { href: "/dashboard/audit", label: "Audit log", icon: ScrollText, tour: "audit" },
  { href: "/dashboard/webhooks", label: "Webhooks", icon: Webhook, tour: "webhooks" },
  { href: "/dashboard/settings", label: "Settings", icon: Settings, tour: "settings" },
];

// Platform-admin only — appended at render time
const ADMIN_NAV = { href: "/dashboard/admin", label: "Admin", icon: ShieldCheck, tour: "admin" };

export function AppShell({ children }: { children: React.ReactNode }) {
  const { me, activeOrgId, switchOrg, logout, can } = useAuth();
  const pathname = usePathname();
  const activeOrg = me?.orgs.find((o) => o.id === activeOrgId);
  // Links the viewer cannot open are hidden (deep links land on PermissionGate).
  const nav = [
    ...NAV.filter(({ href }) => can(ROUTE_PERMISSIONS[href])),
    ...(me?.is_platform_admin ? [ADMIN_NAV] : []),
  ];
  // Mobile menu is open for the page it was opened on: navigating closes it.
  const [menuPath, setMenuPath] = useState<string | null>(null);
  const menuOpen = menuPath === pathname;
  const [switchError, setSwitchError] = useState<string | null>(null);

  async function onSwitchOrg(orgId: string) {
    setSwitchError(null);
    try {
      await switchOrg(orgId);
    } catch (err) {
      setSwitchError(err instanceof Error ? err.message : "Could not switch organization");
    }
  }

  return (
    <div className="flex min-h-screen flex-col bg-white md:flex-row">
      <aside className="flex flex-col border-b border-zinc-200 bg-zinc-50/60 md:w-60 md:shrink-0 md:border-r md:border-b-0">
        <div
          className={`flex h-16 items-center justify-between gap-2 border-zinc-200 px-5 md:border-b ${
            menuOpen ? "border-b" : ""
          }`}
        >
          <BrandMark size="sm" />
          <button
            type="button"
            onClick={() => setMenuPath(menuOpen ? null : pathname)}
            aria-expanded={menuOpen}
            aria-controls="app-menu"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            className="-mr-2 rounded-lg p-2 text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 md:hidden"
          >
            {menuOpen ? <X className="h-5 w-5" aria-hidden /> : <Menu className="h-5 w-5" aria-hidden />}
          </button>
        </div>

        <div id="app-menu" className={`${menuOpen ? "flex" : "hidden"} flex-1 flex-col md:flex`}>
          {me && me.orgs.length > 0 && (
            <div className="border-b border-zinc-200 p-3">
              <label htmlFor="org-switcher" className="sr-only">
                Active organization
              </label>
              {/* Product-tour anchor (components/tour/steps.tsx). */}
              <div className="relative" data-tour="org-switcher">
                <Building2 className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-zinc-400" aria-hidden />
                <select
                  id="org-switcher"
                  value={activeOrgId ?? ""}
                  onChange={(e) => onSwitchOrg(e.target.value)}
                  className="w-full appearance-none rounded-lg border border-zinc-200 bg-white py-2 pl-8 pr-3 text-sm font-medium text-zinc-900 focus:outline-none focus:ring-2 focus:ring-primary"
                >
                  {me.orgs.map((org) => (
                    <option key={org.id} value={org.id}>
                      {org.name}
                    </option>
                  ))}
                </select>
              </div>
              {activeOrg && (
                <p className="mt-1.5 px-1 text-xs text-zinc-400">
                  {activeOrg.slug} · {activeOrg.role_keys.join(", ") || "member"}
                </p>
              )}
              {switchError && (
                <p role="alert" className="mt-1.5 px-1 text-xs text-red-600">
                  {switchError}
                </p>
              )}
              <Link
                href="/onboarding"
                className="mt-2 flex items-center gap-1.5 rounded-md px-1 py-0.5 text-xs font-medium text-zinc-500 hover:text-zinc-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
              >
                <Plus className="h-3.5 w-3.5" aria-hidden />
                New organization
              </Link>
            </div>
          )}

          <nav className="flex-1 space-y-0.5 p-3" aria-label="Main">
            {nav.map(({ href, label, icon: Icon, tour }) => {
              const active = pathname === href;
              return (
                <Link
                  key={href}
                  href={href}
                  data-tour={`nav-${tour}`}
                  aria-current={active ? "page" : undefined}
                  className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm ${
                    active
                      ? "bg-primary font-medium text-primary-foreground"
                      : "text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900"
                  }`}
                >
                  <Icon className="h-4 w-4" aria-hidden />
                  {label}
                </Link>
              );
            })}
          </nav>

          <div className="border-t border-zinc-200 p-3">
            <div className="flex items-center justify-between px-1 pb-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-zinc-900">{me?.display_name}</p>
                <p className="truncate text-xs text-zinc-400">{me?.email}</p>
              </div>
            </div>
            {/* Closes the mobile menu first, so the overlay draws over the page. */}
            <TourButton onStart={() => setMenuPath(null)} />
            <button
              onClick={() => logout()}
              className="w-full rounded-lg border border-zinc-200 px-3 py-1.5 text-sm text-zinc-600 hover:bg-white"
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* tabIndex: focus lands here when the tour closes and its opener is gone. */}
      <main tabIndex={-1} className="min-w-0 flex-1 overflow-x-hidden outline-none">
        <div className="mx-auto max-w-5xl px-4 py-8 sm:px-8 sm:py-10">{children}</div>
      </main>
    </div>
  );
}
