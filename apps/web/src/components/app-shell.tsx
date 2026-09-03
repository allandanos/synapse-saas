"use client";

/* App shell: sidebar nav + org switcher + user menu. Server-style semantic layout. */

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Building2,
  Code2,
  CreditCard,
  KeyRound,
  ScrollText,
  Settings,
  ShieldCheck,
  Users,
  Webhook,
} from "lucide-react";
import { useAuth } from "@/lib/auth-context";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: BarChart3 },
  { href: "/dashboard/members", label: "Members", icon: Users },
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

  return (
    <div className="flex min-h-screen bg-white">
      <aside className="flex w-60 flex-col border-r border-zinc-200 bg-zinc-50/60">
        <div className="flex h-16 items-center gap-2 border-b border-zinc-200 px-5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-zinc-900 text-xs font-bold text-white">
            S
          </div>
          <span className="text-sm font-semibold tracking-tight">Synapse</span>
        </div>

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
                className="w-full appearance-none rounded-lg border border-zinc-200 bg-white py-2 pl-8 pr-3 text-sm font-medium text-zinc-900 focus:outline-none focus:ring-2 focus:ring-zinc-900"
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
                    ? "bg-zinc-900 font-medium text-white"
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
      </aside>

      <main className="flex-1 overflow-x-hidden">
        <div className="mx-auto max-w-5xl px-8 py-10">{children}</div>
      </main>
    </div>
  );
}
