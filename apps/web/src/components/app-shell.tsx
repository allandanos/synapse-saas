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
  ScrollText,
  Settings,
  ShieldCheck,
  Users,
  Webhook,
  X,
} from "lucide-react";
import { BrandMark } from "@/components/brand-mark";
import { useAuth } from "@/lib/auth-context";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: BarChart3 },
  { href: "/dashboard/members", label: "Members", icon: Users },
  { href: "/dashboard/agents", label: "Agents", icon: Bot },
  { href: "/dashboard/billing", label: "Billing", icon: CreditCard },
  { href: "/dashboard/api-keys", label: "API keys", icon: KeyRound },
  { href: "/dashboard/developer", label: "Developer", icon: Code2 },
  { href: "/dashboard/usage", label: "Usage", icon: BarChart3 },
  { href: "/dashboard/audit", label: "Audit log", icon: ScrollText },
  { href: "/dashboard/webhooks", label: "Webhooks", icon: Webhook },
  { href: "/dashboard/settings", label: "Settings", icon: Settings },
];

// Platform-admin only — appended at render time
const ADMIN_NAV = { href: "/dashboard/admin", label: "Admin", icon: ShieldCheck };

export function AppShell({ children }: { children: React.ReactNode }) {
  const { me, activeOrgId, switchOrg, logout } = useAuth();
  const pathname = usePathname();
  const activeOrg = me?.orgs.find((o) => o.id === activeOrgId);
  const nav = me?.is_platform_admin ? [...NAV, ADMIN_NAV] : NAV;
  // Mobile menu is open for the page it was opened on: navigating closes it.
  const [menuPath, setMenuPath] = useState<string | null>(null);
  const menuOpen = menuPath === pathname;

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
              <div className="relative">
                <Building2 className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-zinc-400" aria-hidden />
                <select
                  id="org-switcher"
                  value={activeOrgId ?? ""}
                  onChange={(e) => switchOrg(e.target.value)}
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
            </div>
          )}

          <nav className="flex-1 space-y-0.5 p-3" aria-label="Main">
            {nav.map(({ href, label, icon: Icon }) => {
              const active = pathname === href;
              return (
                <Link
                  key={href}
                  href={href}
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
            <button
              onClick={() => logout()}
              className="w-full rounded-lg border border-zinc-200 px-3 py-1.5 text-sm text-zinc-600 hover:bg-white"
            >
              Sign out
            </button>
          </div>
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-x-hidden">
        <div className="mx-auto max-w-5xl px-4 py-8 sm:px-8 sm:py-10">{children}</div>
      </main>
    </div>
  );
}
